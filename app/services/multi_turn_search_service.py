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

LOGGER = logging.getLogger(__name__)

EXTRACTOR_SYSTEM_PROMPT = """你是一个专业的电子元器件标签分析与实体抽取引擎。
你的任务是从杂乱的工业包装袋 OCR 文本中提取标准型号、C 码、品牌、封装与规格属性。
规则约束：
1. 过滤立创销售订单编号 (SO\\d+) 与仓库拣货库位编号 (\\d{4}-\\w+, \\d+/\\d+)。
2. 若检测到工业旧袋复用场景，表面加贴新标签型号优先级高于底层印刷旧底标与作废 C 码。
3. 输出纯 JSON 格式数据。"""

RERANKER_SYSTEM_PROMPT = """你是一个资深的电子硬件工程仲裁专家。
你的任务是在候选元器件列表中进行深层工程比对。
规则约束：
1. 逐项审查型号、品牌、封装兼容性、引脚数与电气参数。
2. 识别工业旧袋复用冲突，加贴新标签优先于底层旧印刷。
3. 决策分为 exact_match、ambiguous、no_match，并给出严谨的排他分析理由 (reasoning)。
4. 输出严格符合 JSON 格式。"""


def extract_json_safely(text: str) -> Dict[str, Any]:
    """Extract first valid balanced JSON object from model output."""
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end != -1:
        try:
            return json.loads(text[start:end])
        except Exception:
            pass
    return {}


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
        client = self.get_extractor_client()

        try:
            resp = client.chat.completions.create(
                model="electronic-qwen-extractor",
                messages=[
                    {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请从以下工业元器件标签 OCR 文本中提取标准型号查询词与封装规格。\n\n{input_text}"},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            gen_text = resp.choices[0].message.content or ""
            parsed = extract_json_safely(gen_text)
            if parsed and ("queries" in parsed or "family" in parsed):
                # Sanity post-processing on physical electrical units
                specs = parsed.get("specs") or {}
                raw_text = input_text.lower()
                has_resistor_val = bool(re.search(r"\b\d+(?:\.\d+)?[kmr]\b", raw_text) or "ω" in raw_text or "resistor" in raw_text)
                has_capacitor_val = bool(re.search(r"\b\d+(?:\.\d+)?[pnuµ]f\b", raw_text) or "mlcc" in raw_text or "capacitor" in raw_text)

                if has_resistor_val and not has_capacitor_val:
                    parsed["family"] = "resistor"
                    specs["category"] = "Resistors"
                    if "capacitance" in specs and "resistance" not in specs:
                        specs["resistance"] = specs.pop("capacitance")
                elif has_capacitor_val and not has_resistor_val:
                    parsed["family"] = "capacitor"
                    specs["category"] = "Capacitors"
                    if "resistance" in specs and "capacitance" not in specs:
                        specs["capacitance"] = specs.pop("resistance")

                parsed["specs"] = specs
                return parsed
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

        return {
            "family": "general",
            "queries": queries,
            "specs": specs,
            "review_reason": "heuristic_fallback"
        }

    def retrieve_candidates(self, mpn: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
        """Retrieve candidate parts from PartShelf databases using tiered relaxation."""
        candidates = []
        seen_keys = set()

        def add_item(item: Dict[str, Any], source: str):
            part_no = (item.get("mfr_part_number") or item.get("mfr") or item.get("lib_reference") or "").strip()
            ext_id = str(item.get("lcsc") or item.get("id") or "")
            key = f"{source}:{ext_id or part_no.upper()}"
            if key in seen_keys:
                return
            seen_keys.add(key)
            name = item.get("mfr") or item.get("lib_reference") or item.get("mfr_part_number") or f"Part {ext_id}"
            candidates.append({
                "library_source": source,
                "external_part_id": ext_id,
                "name": name,
                "mfr_part_number": item.get("mfr_part_number") or item.get("mfr") or name,
                "manufacturer": item.get("manufacturer") or "",
                "package": item.get("package") or "",
                "category": item.get("category") or "",
                "description": item.get("description") or "",
                "stock": item.get("stock", 0),
                "image": item.get("image_url_small") or item.get("image") or "",
                "source": source,
                "raw_item": item
            })

        # 1. Exact MPN search in Altium library
        try:
            altium_res = lib_svc.search_altium(query=mpn, limit=max_candidates)
            for it in altium_res.get("items", []):
                add_item(it, "altium")
        except Exception:
            pass

        # 2. Exact MPN search in JLCParts library
        try:
            jlc_res = lib_svc.search_jlcparts(query=mpn, limit=max_candidates)
            for it in jlc_res.get("items", []):
                add_item(it, "jlcparts")
        except Exception:
            pass

        # 3. Relaxation fallback if candidates < 3
        if len(candidates) < 3 and len(mpn) > 4:
            base_roots = []
            m_root = re.match(r"^([A-Za-z0-9]+?)(?:-[A-Za-z0-9]+|[A-Z]{1,3}\d*R|\d{1,2}[A-Z]{1,2})$", mpn)
            if m_root and len(m_root.group(1)) >= 4:
                base_roots.append(m_root.group(1))
            if not base_roots:
                m_pref = re.match(r"^([A-Za-z]{2,}\d+)", mpn)
                if m_pref:
                    base_roots.append(m_pref.group(1))

            for root in base_roots:
                if len(candidates) >= max_candidates:
                    break
                try:
                    rel_res = lib_svc.search_jlcparts(query=root, limit=max_candidates)
                    for it in rel_res.get("items", []):
                        add_item(it, "jlcparts")
                except Exception:
                    pass
                try:
                    rel_alt = lib_svc.search_altium(query=root, limit=max_candidates)
                    for it in rel_alt.get("items", []):
                        add_item(it, "altium")
                except Exception:
                    pass

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

        client = self.get_reranker_client()
        try:
            resp = client.chat.completions.create(
                model="electronic-qwen-reranker",
                messages=[
                    {"role": "system", "content": RERANKER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请根据工业标签信息与检索候选项列表，进行专业技术比对与排他分析，输出裁决理由与结构化决策。\n\n{prompt}"},
                ],
                temperature=0.1,
                max_tokens=400,
            )
            gen_text = resp.choices[0].message.content or ""
            parsed = extract_json_safely(gen_text)
            if parsed and "decision" in parsed:
                dec = str(parsed.get("decision", "")).strip().lower()
                if dec not in ("exact_match", "ambiguous", "no_match"):
                    dec = "no_match"
                parsed["decision"] = dec
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
                    or target_mpn in c_mpn
                    or c_mpn in target_mpn
                )
            )

            if is_mpn_matched:
                if not target_pkg or target_pkg in c_pkg or c_pkg in target_pkg:
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
        """Execute complete multi-turn retrieval and candidate disambiguation pipeline."""
        t0 = time.time()

        # 1. Stage 1: LLM Extraction
        stage1 = self.stage1_extract(ocr_lines)
        queries = stage1.get("queries", [])
        specs = stage1.get("specs", {})

        # Extract primary MPN and LCSC queries
        primary_mpn = ""
        lcsc_code = ""
        for q in queries:
            k = q.get("kind", "").lower()
            txt = q.get("text", "").strip()
            if k == "lcsc" and not lcsc_code:
                m = re.search(r"\bC\d{4,}\b", txt, re.IGNORECASE)
                if m:
                    lcsc_code = m.group(0).upper()
            elif k == "mpn":
                if not is_logistics_or_shelf_noise(txt) and not primary_mpn:
                    primary_mpn = txt

        # 2. Check if authoritative LCSC C-code lookup is valid
        short_circuit_lcsc = False
        lcsc_matched_item = None
        if lcsc_code:
            try:
                jlc_res = lib_svc.search_jlcparts(query=lcsc_code, limit=1)
                if jlc_res.get("items"):
                    lcsc_matched_item = jlc_res["items"][0]
                    if not primary_mpn:
                        short_circuit_lcsc = True
                    else:
                        mfr_code = (lcsc_matched_item.get("mfr") or lcsc_matched_item.get("mfr_part_number") or "").upper()
                        if primary_mpn.upper() in mfr_code or mfr_code in primary_mpn.upper():
                            short_circuit_lcsc = True
                        else:
                            # Reused bag conflict: foreground label differs from bag C-code
                            short_circuit_lcsc = False
            except Exception:
                pass

        if short_circuit_lcsc and lcsc_matched_item:
            return {
                "status": "success",
                "route": "direct_lcsc_match",
                "decision": "exact_match",
                "selected_component": {
                    "library_source": "jlcparts",
                    "external_part_id": str(lcsc_matched_item.get("lcsc") or ""),
                    "name": lcsc_matched_item.get("mfr") or f"C{lcsc_matched_item.get('lcsc')}",
                    "mfr_part_number": lcsc_matched_item.get("mfr") or "",
                    "package": lcsc_matched_item.get("package") or "",
                    "manufacturer": lcsc_matched_item.get("manufacturer") or "",
                    "description": lcsc_matched_item.get("description") or "",
                    "stock": lcsc_matched_item.get("stock", 0),
                    "source": "jlcparts",
                    "image": lcsc_matched_item.get("image_url_small") or "",
                    "raw_item": lcsc_matched_item,
                },
                "candidate_components": [],
                "reasoning": f"标签包含明确立创 C 码 [{lcsc_code}]，与物料型号相符，直接命中实物。",
                "stage1_extraction": stage1,
                "latency_ms": round((time.time() - t0) * 1000, 1)
            }

        # 3. Stage 2 Candidate Retrieval
        mpn_candidates = []
        for q in queries:
            if q.get("kind") == "mpn":
                txt = q.get("text", "").strip()
                if txt and not is_logistics_or_shelf_noise(txt):
                    if txt not in mpn_candidates:
                        mpn_candidates.append(txt)
                    words = [w for w in txt.split() if len(w) >= 4 and not is_logistics_or_shelf_noise(w)]
                    for w in words:
                        if w not in mpn_candidates:
                            mpn_candidates.append(w)

        # Also extract strong alphanumeric MPN candidates from raw OCR lines
        for l in ocr_lines:
            clean_l = l.strip()
            if not is_logistics_or_shelf_noise(clean_l):
                for tok in re.findall(r"\b[A-Za-z0-9._/+-]{5,35}\b", clean_l):
                    if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok) and not is_logistics_or_shelf_noise(tok):
                        if tok not in mpn_candidates:
                            mpn_candidates.append(tok)

        # Sort candidates: prioritize tokens containing BOTH digits and letters, and longer specific strings
        mpn_candidates.sort(
            key=lambda s: (
                bool(re.search(r"\d", s) and re.search(r"[A-Za-z]", s)),
                len(s)
            ),
            reverse=True,
        )

        candidates = []
        for test_mpn in mpn_candidates:
            cands = self.retrieve_candidates(test_mpn, max_candidates=5)
            if cands:
                candidates = cands
                primary_mpn = test_mpn
                break

        if not candidates and primary_mpn:
            candidates = self.retrieve_candidates(primary_mpn, max_candidates=5)
        if not candidates and ocr_lines:
            for l in ocr_lines:
                clean_l = l.strip()
                if clean_l and not is_logistics_or_shelf_noise(clean_l):
                    cands = self.retrieve_candidates(clean_l, max_candidates=5)
                    if cands:
                        candidates = cands
                        primary_mpn = clean_l
                        break

        # Conflicted LCSC item from a reused bag is added as candidate for Reranker to analyze and reject
        if lcsc_matched_item and not short_circuit_lcsc:
            candidates.insert(0, {
                "mfr_part_number": lcsc_matched_item.get("mfr") or lcsc_matched_item.get("mfr_part_number") or "",
                "manufacturer": lcsc_matched_item.get("manufacturer") or "",
                "package": lcsc_matched_item.get("package") or "",
                "category": lcsc_matched_item.get("category") or "",
                "description": f"[底层旧包装印刷C码 {lcsc_code}] " + (lcsc_matched_item.get("description") or ""),
                "source": "jlcparts",
                "raw_item": lcsc_matched_item
            })

        if not candidates:
            return {
                "status": "success",
                "route": "empty_candidates",
                "decision": "no_match",
                "selected_component": None,
                "candidate_components": [],
                "reasoning": f"未能在本地元器件库中检索到型号 [{primary_mpn}] 及其衍生系列的有效候选。",
                "stage1_extraction": stage1,
                "latency_ms": round((time.time() - t0) * 1000, 1)
            }

        # 4. Stage 2 Reranking & Disambiguation
        label_ctx = {
            "ocr_text": "\n".join(ocr_lines),
            "extracted_mpn": primary_mpn,
            "extracted_brand": stage1.get("specs", {}).get("manufacturer", ""),
            "extracted_package": specs.get("package", ""),
            "extracted_category": stage1.get("family", ""),
            "packaging_note": f"检测到底层印刷旧 C 码 [{lcsc_code}] 与加贴新标签型号 [{primary_mpn}] 存在品类冲突。工业规则：加贴新标签优先级高于印刷旧底标。" if (lcsc_matched_item and not short_circuit_lcsc) else ""
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
            "stage1_extraction": stage1,
            "stage2_decision": stage2,
            "latency_ms": round((time.time() - t0) * 1000, 1)
        }

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
                    if not mpn or mpn.upper() in item_mpn or item_mpn in mpn.upper():
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
