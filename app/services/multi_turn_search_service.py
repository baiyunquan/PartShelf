"""Multi-Turn Agentic Search Service for PartShelf.

Orchestrates the two-stage interactive retrieval loop using local llama.cpp servers:
Stage 1: Extract standardized MPN, package, and specifications from label OCR via llama-server (OpenAI API).
- Short-circuit: If an authoritative LCSC C-code is identified, query real-time API/DB directly.
Stage 2 (for non-LCSC / general parts):
- Retrieve candidates from Altium and JLCParts (exact MPN prioritized, with automatic relaxation fallback).
- Run Stage 2 Reranker model via llama-server (OpenAI API) to perform expert CoT technical comparison:
  * Select exact match if fully compatible
  * List plausible candidates if ambiguous / multiple compatible variants
  * Exclude irrelevant / conflicting parts with detailed rationale
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import openai
from openai import OpenAI

from app.core.config import settings
from app.services import external_library_service as lib_svc
from app.services.scan_evidence import contains_model, lcsc_codes, model_key, model_tokens, package_key
from app.services.electrical_value_service import parse_measurements

LOGGER = logging.getLogger(__name__)

EXTRACTOR_SYSTEM_PROMPT = """你是一个专业的电子元器件标签分析与实体抽取引擎。
你的任务是从杂乱的工业包装袋 OCR 文本中提取标准型号、C 码、品牌、封装与规格属性。
规则约束：
1. 过滤立创销售订单编号 (SO\\d+) 与仓库拣货库位编号 (\\d{4}-\\w+, \\d+/\\d+)。
2. 只能提取原文实际出现的型号与参数，不得推测封装、电压、品类或修改型号字符。多个型号或数量并存时记录冲突，不得猜测哪张标签有效。
3. 保留完整型号后缀。缺失的规格使用 null。输出符合给定 JSON Schema 的 JSON。"""

RERANKER_SYSTEM_PROMPT = """你是一个资深的电子硬件工程仲裁专家。
你的任务是在候选元器件列表中进行深层工程比对。
规则约束：
1. 逐项审查型号、品牌、封装兼容性、引脚数与电气参数。
2. 型号后缀不同不能判为精确匹配。多标签冲突须人工核查，不得猜测标签的新旧关系。
3. 决策分为 exact_match、ambiguous、no_match，并给出严谨的排他分析理由 (reasoning)。
4. 输出符合给定 JSON Schema 的 JSON，reasoning 不超过 120 字，不输出长篇思考过程。"""


def extract_json_safely(text: str) -> Dict[str, Any]:
    """Extract first valid balanced JSON object from model output."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return {}


SPEC_FIELDS = ("package", "value", "manufacturer", "resistance", "capacitance", "inductance",
               "voltage", "voltage_rating", "current", "power", "power_rating", "tolerance")
EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "family": {"type": "string", "enum": ["resistor", "capacitor", "inductor", "ic", "connector", "mechanical", "general", "unknown"]},
        "queries": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"kind": {"type": "string", "enum": ["lcsc", "mpn", "value", "package"]},
                           "text": {"type": "string", "maxLength": 64}}, "required": ["kind", "text"]}},
        "specs": {"type": "object", "additionalProperties": False,
                  "properties": {key: {"type": ["string", "null"], "maxLength": 48} for key in ("package", "value", "manufacturer")},
                  "required": ["package", "value", "manufacturer"]},
        "review_reason": {"type": ["string", "null"], "maxLength": 40}},
    "required": ["family", "queries", "specs", "review_reason"]}
RERANK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["exact_match", "ambiguous", "no_match"]},
        "selected_index": {"type": ["integer", "null"], "minimum": 1},
        "candidate_indices": {"type": ["array", "null"], "items": {"type": "integer", "minimum": 1}, "maxItems": 10},
        "reasoning": {"type": "string", "maxLength": 120},
        "excluded": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"index": {"type": "integer", "minimum": 1}, "reason": {"type": "string", "maxLength": 80}},
            "required": ["index", "reason"]}}},
    "required": ["decision", "selected_index", "candidate_indices", "reasoning", "excluded"]}


def structured_format(name, schema):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def completed_json(response):
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise ValueError("Model output is incomplete")
    parsed = extract_json_safely(response.choices[0].message.content or "")
    if not parsed:
        raise ValueError("Model did not return a valid JSON object")
    return parsed


def grounded_extraction(parsed, lines):
    text = "\n".join(lines)
    codes = lcsc_codes(lines)
    queries = []
    for query in parsed.get("queries", []):
        if not isinstance(query, dict):
            continue
        value, kind = str(query.get("text") or ""), str(query.get("kind") or "").lower()
        observed = (value.upper() in codes if kind == "lcsc" else
                    contains_model(text, value) and bool(model_tokens([value])) if kind == "mpn" else
                    model_key(value) in model_key(text) if value else False)
        if observed and kind in {"lcsc", "mpn", "value", "package"}:
            normalized_query = {"kind": kind, "text": value}
            if normalized_query not in queries:
                queries.append(normalized_query)
    specs = {}
    observed_values = {(m.kind, m.value) for line in lines for m in parse_measurements(line)}
    for key, value in (parsed.get("specs") or {}).items():
        if key not in SPEC_FIELDS or not isinstance(value, str) or not value.strip():
            continue
        values = {(m.kind, m.value) for m in parse_measurements(value)}
        if model_key(value) in model_key(text) or (values and values <= observed_values):
            specs[key] = value
    return {**parsed, "queries": queries, "specs": specs}


def is_logistics_or_shelf_noise(s: str) -> bool:
    """Negative patterns for logistics, picking racks, sorting slots, and internal barcodes."""
    s_clean = s.strip()
    # SO26... (JLCPCB sales order number)
    if re.match(r"^SO\d+", s_clean, re.I):
        return True
    # Rack / bin / shelf codes e.g. 0703-0204, 3240-B-D07-001, 3229-B-E04-002, 2352-B-D08-003
    if re.match(r"^\d{4}[-/][A-Za-z0-9]", s_clean):
        return True
    # Sorting slot tickets e.g. 3153/29, 2123/4, 2125/15, 3323/18, 4148/13, 2/27, 18/27
    if re.match(r"^\d{1,4}/\d{1,3}\.?$", s_clean):
        return True
    # Pure numeric barcodes or line numbers e.g. 18, 5004454, 4759797, 88163, 136962
    if re.match(r"^\d{1,10}$", s_clean):
        return True
    # Barcode artifacts e.g. BARCODE-111, PLAIN-BARCODE-12345
    if re.search(r"BARCODE", s_clean, re.I):
        return True
    # Cabinet tags e.g. 柜号: 15, 批次: 123456
    if re.match(r"^(?:柜号|批次|单据号|数量|QTY)[:：]?", s_clean):
        return True
    return False


class MultiTurnSearchService:
    """Service handling multi-turn LLM agentic search and candidate reranking via llama-server."""

    def __init__(
        self,
        extractor_base_url: Optional[str] = None,
        reranker_base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        strict_mode: Optional[bool] = None,
    ):
        self.extractor_base_url = extractor_base_url or settings.LLAMA_EXTRACTOR_BASE_URL
        self.reranker_base_url = reranker_base_url or settings.LLAMA_RERANKER_BASE_URL
        self.api_key = api_key or settings.LLAMA_API_KEY
        self.timeout = timeout if timeout is not None else settings.LLAMA_TIMEOUT_SECONDS
        self.strict_mode = strict_mode if strict_mode is not None else settings.LLAMA_STRICT_MODE
        self._extractor_client: Optional[OpenAI] = None
        self._reranker_client: Optional[OpenAI] = None

    def get_extractor_client(self) -> OpenAI:
        """Lazy client for Stage 1 Extractor llama-server."""
        if self._extractor_client is None:
            import httpx
            self._extractor_client = OpenAI(
                base_url=self.extractor_base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                http_client=httpx.Client(trust_env=False, timeout=self.timeout),
            )
        return self._extractor_client

    def get_reranker_client(self) -> OpenAI:
        """Lazy client for Stage 2 Reranker llama-server."""
        if self._reranker_client is None:
            import httpx
            self._reranker_client = OpenAI(
                base_url=self.reranker_base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                http_client=httpx.Client(trust_env=False, timeout=self.timeout),
            )
        return self._reranker_client

    def stage1_extract(self, ocr_lines: List[str]) -> Dict[str, Any]:
        """Stage 1: Extract normalized queries and specifications from OCR lines."""
        if isinstance(ocr_lines, list):
            formatted_lines = []
            for idx, line in enumerate(ocr_lines, start=1):
                s = str(line).strip()
                if not s:
                    continue
                if re.match(r"^\d+[:\.]\s*", s):
                    formatted_lines.append(s)
                else:
                    formatted_lines.append(f"{idx}: {s}")
            input_text = "\n".join(formatted_lines)
        else:
            input_text = str(ocr_lines)
        try:
            client = self.get_extractor_client()
            resp = client.chat.completions.create(
                model="electronic-qwen-extractor",
                messages=[
                    {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请从以下工业元器件标签 OCR 文本中提取标准型号查询词与封装规格。\n\n{input_text}"},
                ],
                temperature=0.1,
                max_tokens=512,
                response_format=structured_format("label_extraction", EXTRACT_SCHEMA),
            )
            parsed = completed_json(resp)
            if not isinstance(parsed.get("queries"), list) or not isinstance(parsed.get("specs"), dict):
                raise ValueError("Invalid label extraction fields")
            return grounded_extraction(parsed, ocr_lines)
        except Exception as e:
            if self.strict_mode:
                raise RuntimeError(
                    f"LLM service unavailable: llama.cpp Extractor server error at {self.extractor_base_url}: {e}"
                ) from e
            LOGGER.warning("Stage 1 Extractor server call failed, falling back to heuristic: %s", e)

        # Fallback heuristic extractor if server is unavailable and strict_mode is False
        queries = []
        specs = {}
        for line in ocr_lines:
            clean = line.strip()
            if not clean:
                continue
            m_c = re.search(r"\bC\d{4,}\b", clean, re.IGNORECASE)
            if m_c:
                queries.append({"kind": "lcsc", "text": m_c.group(0).upper()})
            m_mpn = re.search(r"(?:型号|料号|P/N|MPN)\s*[:：]\s*([A-Za-z0-9._/+-]+)", clean)
            if m_mpn:
                queries.append({"kind": "mpn", "text": m_mpn.group(1).strip()})
            elif not is_logistics_or_shelf_noise(clean):
                tokens = re.findall(r"\b[A-Za-z0-9._/+-]{5,35}\b", clean)
                for tok in tokens:
                    if re.match(r"^[Cc]\d{3,}$", tok):
                        continue
                    if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok) and not is_logistics_or_shelf_noise(tok):
                        queries.append({"kind": "mpn", "text": tok})
                        break

            m_pkg = re.search(r"\b(0402|0603|0805|1206|1210|SOT[-_]?23|SOT[-_]?223|SOP[-_]?8|DIP[-_]?8|LQFP[-_]?\d+|QFN[-_]?\d+)\b", clean, re.IGNORECASE)
            if m_pkg and "package" not in specs:
                specs["package"] = m_pkg.group(0).upper()

            m_val = re.search(r"\b(\d+(?:\.\d+)?\s*(?:[pnumkKMGF]?[Ff]|[kKMmRΩ]?[ΩR]?|[uUnmH]?[Hh]))\b", clean)
            if m_val and "value" not in specs:
                specs["value"] = m_val.group(0)

        return grounded_extraction({"family": "general", "queries": queries, "specs": specs,
                                    "review_reason": "heuristic_fallback"}, ocr_lines)

    @staticmethod
    def candidate(item, source):
        identity = str(item.get("lcsc") if source == "jlcparts" else item.get("id") or "")
        name = item.get("mfr_part_number") or item.get("mfr") or item.get("lib_reference") or f"Part {identity}"
        return {"library_source": source, "source": source, "external_part_id": identity,
                "name": name, "mfr_part_number": name, "manufacturer": item.get("manufacturer") or "",
                "package": item.get("package") or "", "category": item.get("category") or "",
                "description": item.get("description") or "", "stock": item.get("stock", 0),
                "image": item.get("image_url_small") or item.get("image") or "", "raw_item": item}

    @staticmethod
    def deduplicate(candidates):
        result, seen = [], set()
        # Prefer the supplier catalog when another library references exactly the same part.
        for candidate in sorted(candidates, key=lambda c: c.get("library_source") != "jlcparts"):
            raw = candidate.get("raw_item") or candidate
            source = candidate.get("library_source") or candidate.get("source")
            code = raw.get("lcsc") if source == "jlcparts" else raw.get("lcsc_part")
            if code and re.fullmatch(r"C?\d{3,10}", str(code), re.I):
                key = ("lcsc", str(code).lstrip("Cc"), model_key(candidate.get("mfr_part_number")), package_key(candidate.get("package")))
            else:
                key = (source, candidate.get("external_part_id"))
            if key not in seen:
                result.append(candidate)
                seen.add(key)
        return result

    def retrieve_candidates(self, mpn: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
        """Query full models before fuzzy or unit-equivalent search; merge supplier references."""
        exact = []
        target = model_key(mpn)
        if not target:
            return []
        for source, path, table, fields in (
            ("jlcparts", lib_svc.JLCPARTS_DB_PATH, "jlc_components", ("mfr",)),
            ("altium", lib_svc.ALTIUM_DB_PATH, "altium_components", ("mfr_part_number", "lib_reference")),
        ):
            connection = lib_svc.get_connection(path)
            if connection is None:
                continue
            try:
                available = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                fields = [field for field in fields if field in available]
                if fields:
                    where = " OR ".join(f"{field} = ? COLLATE NOCASE" for field in fields)
                    rows = connection.execute(f"SELECT * FROM {table} WHERE {where} LIMIT ?", [target] * len(fields) + [200])
                    exact.extend(self.candidate(dict(row), source) for row in rows)
            finally:
                connection.close()
        if exact:
            return self.deduplicate(exact)[:max_candidates]
        candidates = []
        for source, search in (("jlcparts", lib_svc.search_jlcparts), ("altium", lib_svc.search_altium)):
            try:
                candidates.extend(self.candidate(row, source) for row in search(query=mpn, limit=30).get("items", []))
            except Exception:
                LOGGER.debug("Catalog search unavailable for %s", source, exc_info=True)
        # Relax only after a complete model lookup fails; never silently replace the observed model.
        if not candidates and model_tokens([mpn]):
            match = re.match(r"^([A-Za-z]{2,}\d+)", target)
            if match and len(match.group(1)) >= 4 and match.group(1) != target:
                for source, search in (("jlcparts", lib_svc.search_jlcparts), ("altium", lib_svc.search_altium)):
                    try:
                        candidates.extend(self.candidate(row, source) for row in search(query=match.group(1), limit=10).get("items", []))
                    except Exception:
                        LOGGER.debug("Relaxed catalog search unavailable", exc_info=True)
        candidates = self.deduplicate(candidates)
        candidates.sort(key=lambda c: model_key(c["mfr_part_number"]) != target)
        return candidates[:max_candidates]

    def stage2_rerank(self, label_context: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Stage 2: Evaluate candidates with CoT comparison and return tri-state decision."""
        if not candidates:
            return {
                "decision": "no_match",
                "reasoning": "未检索到任何相关的元器件候选条目。",
                "selected_index": None,
                "candidate_indices": None,
                "excluded": []
            }

        numbered_cands = []
        for idx, c in enumerate(candidates):
            c_copy = dict(c)
            c_copy["index"] = idx + 1
            numbered_cands.append(c_copy)

        prompt = f"标签信息:\n- OCR文本:\n{label_context.get('ocr_text', '')}\n"
        if label_context.get("extracted_mpn"):
            prompt += f"- 提取主型号: {label_context['extracted_mpn']}\n"
        if label_context.get("extracted_brand"):
            prompt += f"- 提取品牌: {label_context['extracted_brand']}\n"
        if label_context.get("extracted_package"):
            prompt += f"- 提取封装: {label_context['extracted_package']}\n"
        if label_context.get("extracted_category"):
            prompt += f"- 提取品类: {label_context['extracted_category']}\n"
        if label_context.get("packaging_note"):
            prompt += f"- 包装与优先级说明: {label_context['packaging_note']}\n"

        prompt += "\n数据库检索候选项:\n"
        for c in numbered_cands:
            pkg_raw = c.get("package") or ""
            pkg_display = pkg_raw
            if re.search(r"through[\s_-]?hole|dip|pin header", pkg_raw, re.I):
                if "插件" not in pkg_display:
                    pkg_display = f"{pkg_raw} (插件/直插)"
            elif re.search(r"surface[\s_-]?mount|smd|smt", pkg_raw, re.I):
                if "贴片" not in pkg_display:
                    pkg_display = f"{pkg_raw} (贴片)"
            prompt += f"[候选 {c['index']}] 型号: {c['mfr_part_number']} | 品牌: {c['manufacturer']} | 封装: {pkg_display} | 品类: {c['category']} | 描述: {c['description']}\n"

        try:
            client = self.get_reranker_client()
            resp = client.chat.completions.create(
                model="electronic-qwen-reranker",
                messages=[
                    {"role": "system", "content": RERANKER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请根据工业标签信息与检索候选项列表，进行专业技术比对与排他分析，输出裁决理由与结构化决策。\n\n{prompt}"},
                ],
                temperature=0.1,
                max_tokens=1200,
                response_format=structured_format("candidate_decision", RERANK_SCHEMA),
            )
            parsed = completed_json(resp)
            decision = parsed.get("decision")
            index = parsed.get("selected_index")
            if decision not in {"exact_match", "ambiguous", "no_match"}:
                raise ValueError("Invalid candidate decision")
            if decision == "exact_match" and (type(index) is not int or not 1 <= index <= len(candidates)):
                raise ValueError("Invalid selected candidate")
            if any(type(i) is not int or not 1 <= i <= len(candidates) for i in (parsed.get("candidate_indices") or [])):
                raise ValueError("Invalid candidate indices")
            parsed["reasoning"] = str(parsed.get("reasoning") or "")[:120]
            return parsed
        except Exception as e:
            if self.strict_mode:
                raise RuntimeError(
                    f"LLM service unavailable: llama.cpp Reranker server error at {self.reranker_base_url}: {e}"
                ) from e
            LOGGER.warning("Stage 2 Reranker server call failed, falling back to rule-based evaluator: %s", e)

        # Fallback rule-based evaluator if Reranker server unavailable and strict_mode is False
        target_mpn = (label_context.get("extracted_mpn") or "").strip().upper()
        target_pkg = (label_context.get("extracted_package") or "").strip().upper()
        target_val = (label_context.get("extracted_value") or "").strip().upper()

        matching_indices = []
        excluded = []
        for c in numbered_cands:
            c_mpn = (c.get("mfr_part_number") or c.get("name") or "").upper()
            c_pkg = (c.get("package") or "").upper()
            c_desc = (c.get("description") or "").upper()
            c_ext = str(c.get("external_part_id") or c.get("lcsc") or "").upper()
            c_code_str = f"C{c_ext}" if c_ext else ""

            is_mpn_matched = bool(
                target_mpn and (
                    target_mpn in (c_mpn, c_code_str, c_ext)
                )
            )

            if is_mpn_matched:
                if not target_pkg or package_key(target_pkg) == package_key(c_pkg):
                    matching_indices.append(c["index"])
                else:
                    excluded.append({"index": c["index"], "reason": f"封装不匹配 ({c_pkg} vs {target_pkg})"})
            elif not target_mpn and target_val:
                if (target_val in c_desc or target_val in c_mpn) and (not target_pkg or target_pkg in c_pkg or c_pkg in target_pkg):
                    matching_indices.append(c["index"])
                elif not (target_val in c_desc or target_val in c_mpn):
                    excluded.append({"index": c["index"], "reason": f"标称参数不匹配 ({target_val})"})
                else:
                    excluded.append({"index": c["index"], "reason": f"封装不匹配 ({c_pkg} vs {target_pkg})"})
            else:
                excluded.append({"index": c["index"], "reason": f"型号不匹配 ({c_mpn} vs {target_mpn})"})

        if len(matching_indices) == 1:
            return {
                "decision": "exact_match",
                "selected_index": matching_indices[0],
                "candidate_indices": None,
                "reasoning": f"候选条目 {matching_indices[0]} 与标签主型号及封装精确吻合。",
                "excluded": excluded
            }
        elif len(matching_indices) > 1:
            return {
                "decision": "ambiguous",
                "selected_index": None,
                "candidate_indices": matching_indices,
                "reasoning": f"存在多个功能兼容候选条目 ({matching_indices})，需进一步确认后缀规格。",
                "excluded": excluded
            }
        else:
            return {
                "decision": "no_match",
                "selected_index": None,
                "candidate_indices": None,
                "reasoning": "所有候选条目均与标签规格存在硬性冲突。",
                "excluded": excluded
            }

    def process(self, ocr_lines: List[str]) -> Dict[str, Any]:
        """Reuse OCR text; exact C-codes and full observed models precede specification search."""
        started = time.time()
        codes, observed = lcsc_codes(ocr_lines), model_tokens(ocr_lines)
        code_candidates = []
        for code in codes[:8]:
            try:
                item = lib_svc.get_jlcparts_component(int(code[1:]))
                if item:
                    code_candidates.append(self.candidate(item, "jlcparts"))
            except Exception:
                LOGGER.warning("Exact supplier lookup failed for %s", code, exc_info=True)
        if len(codes) == len(code_candidates) == 1:
            candidate = code_candidates[0]
            if all(model_key(token) == model_key(candidate["mfr_part_number"]) for token in observed):
                return {"status": "success", "route": "direct_lcsc_match", "decision": "exact_match",
                        "selected_component": candidate, "candidate_components": [],
                        "reasoning": f"原文立创编号 {codes[0]} 与型号无冲突。",
                        "latency_ms": round((time.time() - started) * 1000, 1)}

        stage1 = self.stage1_extract(ocr_lines)
        queries, specs = stage1.get("queries", []), stage1.get("specs", {})
        models = list(dict.fromkeys([model_key(q["text"]) for q in queries if q.get("kind") == "mpn"] + observed))
        candidates = list(code_candidates)
        for model in models[:6]:
            candidates.extend(self.retrieve_candidates(model, max_candidates=8))
        if not candidates:
            value = specs.get("value") or specs.get("capacitance") or specs.get("resistance") or specs.get("inductance")
            if value:
                query = " ".join(filter(None, [value, specs.get("package")]))
                candidates.extend(self.retrieve_candidates(query, max_candidates=8))
        candidates = self.deduplicate(candidates)[:10]
        if not candidates:
            return {"status": "success", "route": "empty_candidates", "decision": "no_match",
                    "selected_component": None, "candidate_components": [], "reasoning": "未找到原文型号或明确规格对应的目录记录。",
                    "stage1_extraction": stage1, "latency_ms": round((time.time() - started) * 1000, 1)}
        context = {"ocr_text": "\n".join(ocr_lines), "extracted_mpn": models[0] if models else "",
                   "extracted_brand": specs.get("manufacturer", ""), "extracted_package": specs.get("package", ""),
                   "extracted_value": specs.get("value", ""), "extracted_category": stage1.get("family", ""),
                   "packaging_note": "存在多个型号或编号，需人工核查。" if len(models) > 1 or len(codes) > 1 else ""}
        stage2 = self.stage2_rerank(context, candidates)
        decision, index = stage2.get("decision", "no_match"), stage2.get("selected_index")
        selected = candidates[index - 1] if decision == "exact_match" and type(index) is int and 1 <= index <= len(candidates) else None
        ambiguous = [candidates[i - 1] for i in (stage2.get("candidate_indices") or []) if type(i) is int and 1 <= i <= len(candidates)]
        return {"status": "success", "route": "reranker_adjudicated", "decision": decision,
                "selected_component": selected, "candidate_components": ambiguous if decision == "ambiguous" else [],
                "reasoning": stage2.get("reasoning", ""), "excluded": stage2.get("excluded", []),
                "all_retrieved_candidates": candidates, "stage1_extraction": stage1, "stage2_decision": stage2,
                "latency_ms": round((time.time() - started) * 1000, 1)}

    def process_bom_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Execute multi-turn retrieval and candidate disambiguation for a structured BOM row."""
        t0 = time.time()
        mpn = (row.get("manufacturer_part") or "").strip()
        comment = (row.get("comment") or "").strip()
        val = (row.get("value") or "").strip()
        pkg = (row.get("footprint") or row.get("package") or "").strip()
        supplier_part = (row.get("supplier_part") or "").strip()
        brand = (row.get("manufacturer") or "").strip()
        designator = (row.get("designator") or "").strip()

        # Check LCSC C-code fast path
        c_code = None
        for cand in [supplier_part, mpn, comment]:
            m = re.search(r"\bC(\d{3,10})\b", cand, re.I)
            if m:
                c_code = f"C{m.group(1)}"
                break

        row_lines = []
        if c_code:
            row_lines.append(f"LCSC: {c_code}")
        if mpn:
            row_lines.append(f"MPN: {mpn}")
        if val:
            row_lines.append(f"Value: {val}")
        if comment and comment != mpn and comment != val:
            row_lines.append(f"Comment: {comment}")
        if pkg:
            row_lines.append(f"Package: {pkg}")
        if brand:
            row_lines.append(f"Brand: {brand}")
        if designator:
            row_lines.append(f"Designator: {designator}")

        # If C-code is found, check if it's valid in jlcparts
        if c_code:
            try:
                jlc_res = lib_svc.search_jlcparts(query=c_code, limit=1)
                if jlc_res.get("items"):
                    item = jlc_res["items"][0]
                    item_mpn = (item.get("mfr") or "").upper()
                    if not mpn or model_key(mpn) == model_key(item_mpn):
                        return {
                            "status": "success",
                            "route": "direct_lcsc_match",
                            "decision": "exact_match",
                            "selected_component": {
                                "library_source": "jlcparts",
                                "external_part_id": str(item["lcsc"]),
                                "name": item.get("mfr") or f"C{item['lcsc']}",
                                "mfr_part_number": item.get("mfr") or "",
                                "package": item.get("package") or "",
                                "manufacturer": item.get("manufacturer") or "",
                                "description": item.get("description") or "",
                                "stock": item.get("stock", 0),
                                "source": "jlcparts",
                                "image": item.get("image_url_small") or "",
                                "raw_item": item,
                            },
                            "candidate_components": [],
                            "reasoning": f"BOM 行包含权威立创编号 [{c_code}]，与器件型号匹配，直接命中库中元器件。",
                            "latency_ms": round((time.time() - t0) * 1000, 1)
                        }
            except Exception:
                pass

        # Query candidates using MPN, or fallback to value + pkg / comment
        search_query = mpn or f"{val} {pkg}".strip() or comment
        candidates = self.retrieve_candidates(search_query, max_candidates=5)
        if not candidates and val and pkg and search_query != f"{val} {pkg}":
            candidates = self.retrieve_candidates(f"{val} {pkg}", max_candidates=5)

        if not candidates:
            return {
                "status": "success",
                "route": "empty_candidates",
                "decision": "no_match",
                "selected_component": None,
                "candidate_components": [],
                "reasoning": f"未能在本地元器件库中检索到规格 [{search_query}] 的有效候选。",
                "latency_ms": round((time.time() - t0) * 1000, 1)
            }

        # Stage 2 Reranking
        label_ctx = {
            "ocr_text": "\n".join(row_lines),
            "extracted_mpn": mpn,
            "extracted_brand": brand,
            "extracted_package": pkg,
            "extracted_value": val or comment,
            "extracted_category": row.get("primary_category") or "",
            "packaging_note": ""
        }

        stage2 = self.stage2_rerank(label_ctx, candidates)
        decision = stage2.get("decision", "no_match")
        selected_idx = stage2.get("selected_index")
        cand_indices = stage2.get("candidate_indices") or []

        selected_comp = None
        ambiguous_comps = []

        if decision == "exact_match" and selected_idx and 1 <= selected_idx <= len(candidates):
            selected_comp = candidates[selected_idx - 1]
        elif decision == "ambiguous":
            for idx in cand_indices:
                if 1 <= idx <= len(candidates):
                    ambiguous_comps.append(candidates[idx - 1])
            if not ambiguous_comps and candidates:
                ambiguous_comps = candidates[:3]

        return {
            "status": "success",
            "route": "reranker_adjudicated",
            "decision": decision,
            "selected_component": selected_comp,
            "candidate_components": ambiguous_comps,
            "reasoning": stage2.get("reasoning", ""),
            "excluded": stage2.get("excluded", []),
            "all_retrieved_candidates": candidates,
            "stage2_decision": stage2,
            "latency_ms": round((time.time() - t0) * 1000, 1)
        }


# Singleton service instance
multi_turn_service = MultiTurnSearchService()
