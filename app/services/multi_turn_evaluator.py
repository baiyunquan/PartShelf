"""Stage 1 entity extraction, Stage 2 reranking, and evaluation logic for AI search."""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.services.electrical_value_service import parse_measurements
from app.services.multi_turn_schemas import (
    EXTRACT_SCHEMA,
    EXTRACTOR_SYSTEM_PROMPT,
    RERANK_SCHEMA,
    RERANKER_SYSTEM_PROMPT,
    SPEC_FIELDS,
    completed_json,
    is_logistics_or_shelf_noise,
    structured_format,
)
from app.services.scan_evidence import (
    contains_model,
    lcsc_codes,
    model_key,
    model_tokens,
    package_key,
)

LOGGER = logging.getLogger(__name__)


def grounded_extraction(parsed: Dict[str, Any], lines: List[str]) -> Dict[str, Any]:
    """Validate that extracted models, LCSC codes, and specs are physically present in OCR evidence."""
    text = "\n".join(lines)
    codes = lcsc_codes(lines)
    queries = []
    for query in parsed.get("queries", []):
        if not isinstance(query, dict):
            continue
        value, kind = str(query.get("text") or ""), str(query.get("kind") or "").lower()
        observed = (
            value.upper() in codes
            if kind == "lcsc"
            else contains_model(text, value) and bool(model_tokens([value]))
            if kind == "mpn"
            else model_key(value) in model_key(text)
            if value
            else False
        )
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


def build_rerank_prompt(label_context: Dict[str, Any], numbered_cands: List[Dict[str, Any]]) -> str:
    """Format label context and candidates, automatically expanding package terminology synonyms."""
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
        prompt += f"[候选 {c['index']}] 型号: {c.get('mfr_part_number', '')} | 品牌: {c.get('manufacturer', '')} | 封装: {pkg_display} | 品类: {c.get('category', '')} | 描述: {c.get('description', '')}\n"
    return prompt


def rule_based_rerank_fallback(
    label_context: Dict[str, Any],
    numbered_cands: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fallback rule-based evaluator when Stage 2 Reranker LLM service is offline."""
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
            "excluded": excluded,
        }
    elif len(matching_indices) > 1:
        return {
            "decision": "ambiguous",
            "selected_index": None,
            "candidate_indices": matching_indices,
            "reasoning": f"存在多个功能兼容候选条目 ({matching_indices})，需进一步确认后缀规格。",
            "excluded": excluded,
        }
    else:
        return {
            "decision": "no_match",
            "selected_index": None,
            "candidate_indices": None,
            "reasoning": "所有候选条目均与标签规格存在硬性冲突。",
            "excluded": excluded,
        }


def format_rerank_result(
    decision: str,
    candidates: List[Dict[str, Any]],
    stage2: Dict[str, Any],
    started_time: float,
    route: str = "reranker_adjudicated",
    stage1: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Standardize pipeline return payload for exact_match, ambiguous, or no_match."""
    selected_idx = stage2.get("selected_index")
    cand_indices = stage2.get("candidate_indices") or []

    selected_comp = None
    ambiguous_comps = []

    if decision == "exact_match" and type(selected_idx) is int and 1 <= selected_idx <= len(candidates):
        selected_comp = candidates[selected_idx - 1]
    elif decision == "ambiguous":
        for idx in cand_indices:
            if type(idx) is int and 1 <= idx <= len(candidates):
                ambiguous_comps.append(candidates[idx - 1])
        if not ambiguous_comps and candidates:
            ambiguous_comps = candidates[:3]

    res = {
        "status": "success",
        "route": route,
        "decision": decision,
        "selected_component": selected_comp,
        "candidate_components": ambiguous_comps if decision == "ambiguous" else [],
        "reasoning": stage2.get("reasoning", ""),
        "excluded": stage2.get("excluded", []),
        "all_retrieved_candidates": candidates,
        "stage2_decision": stage2,
        "latency_ms": round((time.time() - started_time) * 1000, 1),
    }
    if stage1 is not None:
        res["stage1_extraction"] = stage1
    return res


def stage1_extract(
    ocr_lines: List[str],
    client: Optional[Any] = None,
    client_getter: Optional[Any] = None,
    strict_mode: bool = False,
    extractor_base_url: str = "",
) -> Dict[str, Any]:
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

    active_client = client
    if active_client is None and client_getter is not None:
        try:
            active_client = client_getter()
        except Exception as e:
            if strict_mode:
                raise RuntimeError(
                    f"LLM service unavailable: llama.cpp Extractor client error at {extractor_base_url}: {e}"
                ) from e
            LOGGER.warning("Stage 1 Extractor client unavailable, falling back to heuristic: %s", e)

    if active_client is not None:
        try:
            resp = active_client.chat.completions.create(
                model="electronic-qwen-extractor",
                messages=[
                    {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请从以下工业元器件标签 OCR 文本中提取标准型号查询词与封装规格。\n\n{input_text}"},
                ],
                temperature=0.1,
                max_tokens=600,
                response_format=structured_format("label_extraction", EXTRACT_SCHEMA),
            )
            parsed = completed_json(resp)
            if parsed and ("queries" in parsed or "family" in parsed):
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
                return grounded_extraction(parsed, ocr_lines)
        except Exception as e:
            if strict_mode:
                raise RuntimeError(
                    f"LLM service unavailable: llama.cpp Extractor server error at {extractor_base_url}: {e}"
                ) from e
            LOGGER.warning("Stage 1 Extractor server call failed, falling back to heuristic: %s", e)
    elif strict_mode:
        raise RuntimeError(
            f"LLM service unavailable: llama.cpp Extractor client is None at {extractor_base_url}"
        )

    # Fallback heuristic extractor
    queries = []
    specs = {}
    for line in ocr_lines:
        clean = line.strip()
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

    return grounded_extraction(
        {"family": "general", "queries": queries, "specs": specs, "review_reason": "heuristic_fallback"},
        ocr_lines,
    )


def stage2_rerank(
    label_context: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    client: Optional[Any] = None,
    client_getter: Optional[Any] = None,
    strict_mode: bool = False,
    reranker_base_url: str = "",
) -> Dict[str, Any]:
    """Stage 2: Evaluate candidates with CoT comparison and return tri-state decision."""
    if not candidates:
        return {
            "decision": "no_match",
            "reasoning": "未检索到任何相关的元器件候选条目。",
            "selected_index": None,
            "candidate_indices": None,
            "excluded": [],
        }

    numbered_cands = []
    for idx, c in enumerate(candidates):
        c_copy = dict(c)
        c_copy["index"] = idx + 1
        numbered_cands.append(c_copy)

    prompt = build_rerank_prompt(label_context, numbered_cands)

    active_client = client
    if active_client is None and client_getter is not None:
        try:
            active_client = client_getter()
        except Exception as e:
            if strict_mode:
                raise RuntimeError(
                    f"LLM service unavailable: llama.cpp Reranker client error at {reranker_base_url}: {e}"
                ) from e
            LOGGER.warning("Stage 2 Reranker client unavailable, falling back to rule-based evaluator: %s", e)

    if active_client is not None:
        try:
            resp = active_client.chat.completions.create(
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
            if strict_mode:
                raise RuntimeError(
                    f"LLM service unavailable: llama.cpp Reranker server error at {reranker_base_url}: {e}"
                ) from e
            LOGGER.warning("Stage 2 Reranker server call failed, falling back to rule-based evaluator: %s", e)
    elif strict_mode:
        raise RuntimeError(
            f"LLM service unavailable: llama.cpp Reranker client is None at {reranker_base_url}"
        )

    return rule_based_rerank_fallback(label_context, numbered_cands)
