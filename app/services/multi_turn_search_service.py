"""Multi-Turn Agentic Search Service for PartShelf.

Orchestrates the two-stage interactive retrieval loop using local llama.cpp servers:
Stage 1: Extract standardized MPN, package, and specifications from label OCR via llama-server.
Stage 2: Retrieve candidates from Altium/JLCParts and run Stage 2 Reranker model for expert CoT adjudication.
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.multi_turn_evaluator import (
    format_rerank_result,
    grounded_extraction,
    stage1_extract,
    stage2_rerank,
)
from app.services.multi_turn_retrieval import (
    deduplicate_candidates,
    fast_path_lcsc_lookup,
    format_candidate,
    retrieve_candidates,
    lookup_lcsc_candidates,
    limit_candidates,
)
from app.services.multi_turn_schemas import (
    EXTRACTOR_SYSTEM_PROMPT,
    RERANKER_SYSTEM_PROMPT,
    SPEC_FIELDS,
    extract_json_safely,
    is_logistics_or_shelf_noise,
)
from app.services.scan_evidence import lcsc_codes, model_key, model_tokens, verify_text

LOGGER = logging.getLogger(__name__)


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
        self.extractor_base_url = extractor_base_url or os.getenv("STAGE1_EXTRACTOR_URL") or settings.LLAMA_EXTRACTOR_BASE_URL
        self.reranker_base_url = reranker_base_url or os.getenv("STAGE2_RERANKER_URL") or settings.LLAMA_RERANKER_BASE_URL
        self.api_key = api_key or settings.LLAMA_API_KEY
        self.timeout = timeout if timeout is not None else settings.LLAMA_TIMEOUT_SECONDS
        self.strict_mode = strict_mode if strict_mode is not None else settings.LLAMA_STRICT_MODE
        self._extractor_client: Optional[OpenAI] = None
        self._reranker_client: Optional[OpenAI] = None

    def get_extractor_client(self) -> OpenAI:
        """Lazy client for Stage 1 Extractor llama-server."""
        if self._extractor_client is None:
            self._extractor_client = OpenAI(
                base_url=self.extractor_base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=0,
                http_client=httpx.Client(trust_env=False, timeout=self.timeout),
            )
        return self._extractor_client

    def get_reranker_client(self) -> OpenAI:
        """Lazy client for Stage 2 Reranker llama-server."""
        if self._reranker_client is None:
            self._reranker_client = OpenAI(
                base_url=self.reranker_base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=0,
                http_client=httpx.Client(trust_env=False, timeout=self.timeout),
            )
        return self._reranker_client

    def stage1_extract(self, ocr_lines: List[str]) -> Dict[str, Any]:
        """Delegate to stage1_extract in multi_turn_evaluator."""
        return stage1_extract(
            ocr_lines=ocr_lines,
            client=self._extractor_client,
            client_getter=self.get_extractor_client,
            strict_mode=self.strict_mode,
            extractor_base_url=self.extractor_base_url,
        )

    def stage2_rerank(self, label_context: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delegate to stage2_rerank in multi_turn_evaluator."""
        return stage2_rerank(
            label_context=label_context,
            candidates=candidates,
            client=self._reranker_client,
            client_getter=self.get_reranker_client,
            strict_mode=self.strict_mode,
            reranker_base_url=self.reranker_base_url,
        )

    def retrieve_candidates(self, mpn: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
        """Delegate to retrieve_candidates in multi_turn_retrieval."""
        return retrieve_candidates(mpn=mpn, max_candidates=max_candidates)

    candidate = staticmethod(format_candidate)
    deduplicate = staticmethod(deduplicate_candidates)

    def process(self, ocr_lines: List[str]) -> Dict[str, Any]:
        """Reuse OCR text; exact C-codes and full observed models precede specification search."""
        started = time.time()
        codes, observed = lcsc_codes(ocr_lines), model_tokens(ocr_lines)
        code_candidates = lookup_lcsc_candidates(codes)

        # 1. Fast-path check: authoritative LCSC C-code directly matching observed model
        fast_match = fast_path_lcsc_lookup(
            c_codes=codes,
            observed_tokens=observed,
            source_label="原文",
            candidates=code_candidates,
        )
        if fast_match:
            fast_match["latency_ms"] = round((time.time() - started) * 1000, 1)
            return fast_match

        # 2. Stage 1 Extraction
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
        candidates = limit_candidates(deduplicate_candidates(candidates), 10)

        supported = [(candidate, verify_text(candidate, ocr_lines)) for candidate in candidates]
        corrections = [(candidate, evidence) for candidate, evidence in supported
                       if evidence.get("verified") and evidence.get("model_correction")]
        if corrections:
            unique = len(corrections) == 1 and not any(c.get("retrieval_truncated") for c in candidates)
            chosen, evidence = corrections[0]
            return {"status":"success", "route":"supported_ocr_correction", "decision":"exact_match" if unique else "ambiguous",
                    "selected_component":chosen if unique else None,
                    "candidate_components":[c for c,_ in corrections] if not unique else [],
                    "all_retrieved_candidates":candidates, "reasoning":"型号的一处字形误读有完整目录、品牌、封装和标值证据支持。" if unique else "多个目录记录支持该字形修正，请核查。",
                    "model_correction":evidence["model_correction"], "stage1_extraction":stage1,
                    "field_evidence":stage1.get("field_evidence", {}),
                    "stages":{"extractor":stage1.get("stage_status", {}), "reranker":{"status":"not_needed"}},
                    "latency_ms":round((time.time()-started)*1000, 1)}

        if not candidates:
            return {
                "status": "success",
                "route": "empty_candidates",
                "decision": "no_match",
                "selected_component": None,
                "candidate_components": [],
                "reasoning": "未找到原文型号或明确规格对应的目录记录。",
                "stage1_extraction": stage1,
                "field_evidence": stage1.get("field_evidence", {}),
                "stages": {"extractor":stage1.get("stage_status", {}), "reranker":{"status":"not_needed"}},
                "latency_ms": round((time.time() - started) * 1000, 1),
            }

        # 3. Stage 2 Reranking
        context = {
            "ocr_text": "\n".join(ocr_lines),
            "extracted_mpn": models[0] if models else "",
            "extracted_brand": specs.get("manufacturer", ""),
            "extracted_package": specs.get("package", ""),
            "extracted_value": specs.get("value", ""),
            "extracted_category": stage1.get("family", ""),
            "packaging_note": "存在多个型号或编号，需人工核查。" if len(models) > 1 or len(codes) > 1 else "",
        }
        stage2 = self.stage2_rerank(context, candidates)
        decision = stage2.get("decision", "no_match")

        return format_rerank_result(
            decision=decision,
            candidates=candidates,
            stage2=stage2,
            started_time=started,
            route="reranker_adjudicated",
            stage1=stage1,
        )

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

        if c_code:
            fast_match = fast_path_lcsc_lookup(
                c_codes=[c_code],
                target_mpn=mpn,
                source_label="BOM 行",
            )
            if fast_match:
                fast_match["latency_ms"] = round((time.time() - t0) * 1000, 1)
                return fast_match

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
                "latency_ms": round((time.time() - t0) * 1000, 1),
            }

        # Stage 2 Reranking
        label_ctx = {
            "ocr_text": "\n".join(row_lines),
            "extracted_mpn": mpn,
            "extracted_brand": brand,
            "extracted_package": pkg,
            "extracted_value": val or comment,
            "extracted_category": row.get("primary_category") or "",
            "packaging_note": "",
        }
        stage2 = self.stage2_rerank(label_ctx, candidates)
        decision = stage2.get("decision", "no_match")

        return format_rerank_result(
            decision=decision,
            candidates=candidates,
            stage2=stage2,
            started_time=t0,
            route="reranker_adjudicated",
        )


# Singleton service instance
multi_turn_service = MultiTurnSearchService()
