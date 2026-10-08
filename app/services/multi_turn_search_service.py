"""Multi-Turn Agentic Search Service for PartShelf.

Orchestrates the two-stage interactive retrieval loop:
Stage 1: Extract standardized MPN, package, and specifications from label OCR.
- Short-circuit: If an authoritative LCSC C-code is identified, query real-time API/DB directly.
Stage 2 (for non-LCSC / general parts):
- Retrieve candidates from Altium and JLCParts (exact MPN prioritized, with automatic relaxation fallback).
- Run Stage 2 Reranker model (or fallback evaluator) to perform expert CoT technical comparison:
  * Select exact match if fully compatible
  * List plausible candidates if ambiguous / multiple compatible variants
  * Exclude irrelevant / conflicting parts with detailed rationale
"""

import os
import re
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from app.services import external_library_service as lib_svc


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


class MultiTurnSearchService:
    """Service handling multi-turn LLM agentic search and candidate reranking."""

    def __init__(self, extractor_adapter_path: Optional[str] = None, reranker_adapter_path: Optional[str] = None):
        round3_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ElectronicQwen/outputs/qwen3.5-2b-distilled-adapter-round3"))
        round2_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ElectronicQwen/outputs/qwen3.5-2b-distilled-adapter-round2"))
        self.extractor_adapter_path = extractor_adapter_path or (round3_path if os.path.exists(round3_path) else round2_path)
        self.reranker_adapter_path = reranker_adapter_path or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../ElectronicQwen/outputs/qwen3.5-2b-reranker-adapter")
        )
        self._extractor_model = None
        self._extractor_tokenizer = None
        self._reranker_model = None
        self._reranker_tokenizer = None

    def _get_extractor(self):
        """Lazy loader for Stage 1 Extractor model."""
        if self._extractor_model is None and os.path.exists(self.extractor_adapter_path):
            try:
                from unsloth import FastLanguageModel
                model, tokenizer = FastLanguageModel.from_pretrained(
                    model_name=self.extractor_adapter_path,
                    max_seq_length=1024,
                    dtype=None,
                    load_in_4bit=False,
                )
                FastLanguageModel.for_inference(model)
                self._extractor_model = model
                self._extractor_tokenizer = tokenizer
            except Exception as e:
                print(f"Warning: Could not load local extractor model: {e}")
        return self._extractor_model, self._extractor_tokenizer

    def _get_reranker(self):
        """Lazy loader for Stage 2 Reranker model."""
        if self._reranker_model is None and os.path.exists(self.reranker_adapter_path):
            try:
                from unsloth import FastLanguageModel
                model, tokenizer = FastLanguageModel.from_pretrained(
                    model_name=self.reranker_adapter_path,
                    max_seq_length=1536,
                    dtype=None,
                    load_in_4bit=False,
                )
                FastLanguageModel.for_inference(model)
                self._reranker_model = model
                self._reranker_tokenizer = tokenizer
            except Exception as e:
                print(f"Warning: Could not load local reranker model: {e}")
        return self._reranker_model, self._reranker_tokenizer

    def stage1_extract(self, ocr_lines: List[str]) -> Dict[str, Any]:
        """Stage 1: Extract normalized queries and specifications from OCR lines."""
        input_text = "\n".join(ocr_lines) if isinstance(ocr_lines, list) else str(ocr_lines)
        model, tokenizer = self._get_extractor()

        if model is not None and tokenizer is not None:
            import torch
            messages = [
                {"role": "user", "content": f"请从以下工业元器件标签 OCR 文本中提取标准型号查询词与封装规格。\n\n{input_text}"}
            ]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(text=[prompt], return_tensors="pt").to("cuda")
            with torch.no_grad():
                out = model.generate(
                    **inputs,
                    max_new_tokens=300,
                    use_cache=True,
                    pad_token_id=tokenizer.eos_token_id,
                    temperature=0.1
                )
            gen_text = tokenizer.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
            parsed = extract_json_safely(gen_text)
            if parsed:
                return parsed

        # Fallback heuristic extractor if local GPU model unavailable
        queries = []
        for line in ocr_lines:
            m_c = re.search(r"\bC\d+\b", line, re.IGNORECASE)
            if m_c:
                queries.append({"kind": "lcsc", "text": m_c.group(0).upper()})
            m_mpn = re.search(r"(?:型号|料号|P/N|MPN)\s*[:：]\s*([A-Za-z0-9._/+-]+)", line)
            if m_mpn:
                queries.append({"kind": "mpn", "text": m_mpn.group(1)})

        return {
            "family": "general",
            "queries": queries,
            "specs": {},
            "review_reason": "heuristic_fallback"
        }

    def retrieve_candidates(self, mpn: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
        """Retrieve candidate parts from PartShelf databases using tiered relaxation."""
        candidates = []
        seen_keys = set()

        def add_item(item: Dict[str, Any], source: str):
            part_no = (item.get("mfr_part_number") or item.get("mfr") or "").strip().upper()
            if not part_no or part_no in seen_keys:
                return
            seen_keys.add(part_no)
            candidates.append({
                "mfr_part_number": item.get("mfr_part_number") or item.get("mfr") or "",
                "manufacturer": item.get("manufacturer") or "",
                "package": item.get("package") or "",
                "category": item.get("category") or "",
                "description": item.get("description") or "",
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
            # Strip trailing ordering/packaging suffixes (e.g. MAX232DR -> MAX232, TLV62569DBVR -> TLV62569)
            base_roots = []
            m_root = re.match(r"^([A-Za-z0-9]+?)(?:-[A-Za-z0-9]+|[A-Z]{1,3}\d*R|\d{1,2}[A-Z]{1,2})$", mpn)
            if m_root and len(m_root.group(1)) >= 4:
                base_roots.append(m_root.group(1))
            # Fallback to general alphanumeric prefix
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
            prompt += f"[候选 {c['index']}] 型号: {c['mfr_part_number']} | 品牌: {c['manufacturer']} | 封装: {c['package']} | 品类: {c['category']} | 描述: {c['description']}\n"

        model, tokenizer = self._get_reranker()
        if model is not None and tokenizer is not None:
            import torch
            messages = [
                {"role": "user", "content": f"请根据工业标签信息与检索候选项列表，进行专业技术比对与排他分析，输出裁决理由与结构化决策。\n\n{prompt}"}
            ]
            full_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(text=[full_prompt], return_tensors="pt").to("cuda")
            with torch.no_grad():
                out = model.generate(
                    **inputs,
                    max_new_tokens=400,
                    use_cache=True,
                    pad_token_id=tokenizer.eos_token_id,
                    temperature=0.1
                )
            gen_text = tokenizer.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
            parsed = extract_json_safely(gen_text)
            if parsed and "decision" in parsed:
                return parsed

        # Fallback rule-based evaluator if Reranker model not yet loaded
        target_mpn = (label_context.get("extracted_mpn") or "").strip().upper()
        target_pkg = (label_context.get("extracted_package") or "").strip().upper()

        matching_indices = []
        excluded = []
        for c in numbered_cands:
            c_mpn = c["mfr_part_number"].upper()
            c_pkg = c["package"].upper()
            if target_mpn and target_mpn == c_mpn:
                matching_indices.append(c["index"])
            elif target_mpn and (target_mpn in c_mpn or c_mpn in target_mpn):
                if not target_pkg or target_pkg in c_pkg or c_pkg in target_pkg:
                    matching_indices.append(c["index"])
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

        # Negative patterns for logistics, picking racks, sorting slots, and internal barcodes
        def is_logistics_or_shelf_noise(s: str) -> bool:
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
            # Cabinet tags e.g. 柜号: 15, 批次: 123456
            if re.match(r"^(?:柜号|批次|单据号|数量|QTY)[:：]?", s_clean):
                return True
            return False

        # Extract primary MPN and LCSC queries
        primary_mpn = ""
        lcsc_code = ""
        for q in queries:
            k = q.get("kind", "").lower()
            txt = q.get("text", "").strip()
            if k == "lcsc" and not lcsc_code:
                # Require strictly C followed by at least 4 digits
                m = re.search(r"\bC\d{4,}\b", txt, re.IGNORECASE)
                if m:
                    lcsc_code = m.group(0).upper()
            elif k == "mpn":
                if not is_logistics_or_shelf_noise(txt) and not primary_mpn:
                    primary_mpn = txt

        # 2. Check if authoritative LCSC C-code lookup is valid
        # If both primary_mpn and lcsc_code exist, verify consistency (reused bag resolution)
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
                        # If C-code matches or shares root with primary_mpn
                        if primary_mpn.upper() in mfr_code or mfr_code in primary_mpn.upper():
                            short_circuit_lcsc = True
                        else:
                            # Reused bag conflict: foreground label differs from bag C-code (e.g. PN7160A1HN vs C49247665)
                            # Do NOT short-circuit! Hand over to Stage 2 Reranker with foreground priority!
                            short_circuit_lcsc = False
            except Exception:
                pass

        if short_circuit_lcsc and lcsc_matched_item:
            return {
                "status": "success",
                "route": "direct_lcsc_match",
                "decision": "exact_match",
                "selected_component": lcsc_matched_item,
                "candidate_components": [],
                "reasoning": f"标签包含明确立创 C 码 [{lcsc_code}]，与物料型号相符，直接命中实物。",
                "stage1_extraction": stage1,
                "latency_ms": round((time.time() - t0) * 1000, 1)
            }

        # 3. Stage 2 Candidate Retrieval (non-LCSC or when C-code conflicted/reused bag)
        candidates = self.retrieve_candidates(primary_mpn or (ocr_lines[0] if ocr_lines else ""), max_candidates=5)

        # If there was a conflicted LCSC item from a reused bag, include it as candidate for Reranker to analyze and reject
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


# Singleton service instance
multi_turn_service = MultiTurnSearchService()
