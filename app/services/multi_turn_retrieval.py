"""Database candidate retrieval, deduplication, and fast-path lookup for AI search."""

import logging
import re
from typing import Any, Dict, List, Optional

from app.services import external_library_service as lib_svc
from app.services.scan_evidence import lcsc_codes, model_key, model_tokens, package_key, manufacturer_key, catalog_specifications, ocr_model_variant

LOGGER = logging.getLogger(__name__)


def format_candidate(item: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Standardize raw candidate dictionary structure across databases."""
    identity = str(item.get("lcsc") if source == "jlcparts" else item.get("id") or "")
    name = item.get("mfr_part_number") or item.get("mfr") or item.get("lib_reference") or f"Part {identity}"
    return {
        "library_source": source,
        "source": source,
        "external_part_id": identity,
        "name": name,
        "mfr_part_number": name,
        "manufacturer": item.get("manufacturer") or "",
        "package": item.get("package") or "",
        "category": item.get("category") or "",
        "description": item.get("description") or "",
        "stock": item.get("stock", 0),
        "image": item.get("image_url_small") or item.get("image") or "",
        "raw_item": item,
    }


# Backward-compatible alias
candidate = format_candidate


def deduplicate_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate candidates, preferring the supplier catalog when another library references the same part."""
    result, groups = [], {}
    for cand in sorted(candidates, key=lambda c: c.get("library_source") != "jlcparts"):
        raw = cand.get("raw_item") or cand
        source = cand.get("library_source") or cand.get("source")
        code = raw.get("lcsc") if source == "jlcparts" else raw.get("lcsc_part")
        if code and re.fullmatch(r"C?\d{3,10}", str(code), re.I):
            key = (
                "lcsc",
                str(code).lstrip("Cc"),
                model_key(cand.get("mfr_part_number")),
            )
        else:
            key = (source, cand.get("external_part_id"))
        equivalent = None
        for previous in groups.get(key, []):
            brand1, brand2 = manufacturer_key(previous.get("manufacturer")), manufacturer_key(cand.get("manufacturer"))
            pkg1, pkg2 = package_key(previous.get("package")), package_key(cand.get("package"))
            specs1, specs2 = catalog_specifications(previous), catalog_specifications(cand)
            if (brand1 and brand2 and brand1 != brand2) or (pkg1 and pkg2 and pkg1 != pkg2):
                continue
            if any(specs1[k] != specs2[k] for k in specs1.keys() & specs2.keys()):
                continue
            equivalent = previous
            break
        if equivalent is None:
            result.append(cand)
            groups.setdefault(key, []).append(cand)
    return result


# Backward-compatible alias
deduplicate = deduplicate_candidates


def enrich_supplier_references(candidates):
    """Resolve declared Altium C references, retaining conflicting metadata for review."""
    enriched = list(candidates)
    present = {str(c.get("external_part_id")) for c in candidates if c.get("library_source") == "jlcparts"}
    checked = set()
    for candidate in candidates:
        raw = candidate.get("raw_item") or candidate
        code = str(raw.get("lcsc_part") or "")
        if candidate.get("library_source") != "altium" or not re.fullmatch(r"C\d{3,10}", code, re.I):
            continue
        numeric = int(code[1:])
        if str(numeric) in present or numeric in checked:
            continue
        checked.add(numeric)
        try:
            item = lib_svc.get_jlcparts_component(numeric)
            if item and str(item.get("lcsc")) == str(numeric) and model_key(item.get("mfr")) == model_key(candidate.get("mfr_part_number")):
                enriched.append(format_candidate(item, "jlcparts"))
                present.add(str(numeric))
        except Exception:
            LOGGER.warning("Supplier reference lookup failed for %s", code, exc_info=True)
    return deduplicate_candidates(enriched)


def retrieve_candidates(mpn: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
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
            valid_fields = [field for field in fields if field in available]
            if valid_fields:
                where = " OR ".join(f"{field} = ? COLLATE NOCASE" for field in valid_fields)
                rows = connection.execute(
                    f"SELECT * FROM {table} WHERE {where} LIMIT ?",
                    [target] * len(valid_fields) + [200],
                )
                exact.extend(format_candidate(dict(row), source) for row in rows)
        finally:
            connection.close()
    if exact:
        return enrich_supplier_references(exact)[:max_candidates]
    # Candidate-only relaxation: change one glyph in the series; preserve the complete suffix.
    approximate, incomplete = [], False
    if len(target) >= 10 and model_tokens([target]):
        escape = lambda value: value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        patterns = [escape(target[:i]) + "_" + escape(target[i+1:]) for i in range(min(6, len(target)))]
        for source, path, table, fields in (
            ("jlcparts", lib_svc.JLCPARTS_DB_PATH, "jlc_components", ("mfr",)),
            ("altium", lib_svc.ALTIUM_DB_PATH, "altium_components", ("mfr_part_number", "lib_reference")),
        ):
            conn = lib_svc.get_connection(path)
            if conn is None:
                continue
            try:
                available = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                valid = [field for field in fields if field in available]
                if valid:
                    where = " OR ".join(f"{field} LIKE ? ESCAPE '\\'" for field in valid for _ in patterns)
                    rows = list(conn.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 201", patterns * len(valid)))
                    incomplete |= len(rows) >= 201
                    for row in rows:
                        item = format_candidate(dict(row), source)
                        if ocr_model_variant(target, item["mfr_part_number"]):
                            item["ocr_model_candidate"] = target
                            approximate.append(item)
            finally:
                conn.close()
    if approximate:
        approximate = enrich_supplier_references(approximate)
        incomplete |= len(approximate) > max_candidates
        if incomplete:
            for item in approximate:
                item["retrieval_truncated"] = True
        return approximate[:max_candidates]
    candidates = []
    for source, search in (("jlcparts", lib_svc.search_jlcparts), ("altium", lib_svc.search_altium)):
        try:
            candidates.extend(
                format_candidate(row, source)
                for row in search(query=mpn, limit=30).get("items", [])
            )
        except Exception:
            LOGGER.debug("Catalog search unavailable for %s", source, exc_info=True)
    # Relax only after a complete model lookup fails; never silently replace the observed model.
    if not candidates and model_tokens([mpn]):
        match = re.match(r"^([A-Za-z]{2,}\d+)", target)
        if match and len(match.group(1)) >= 4 and match.group(1) != target:
            for source, search in (("jlcparts", lib_svc.search_jlcparts), ("altium", lib_svc.search_altium)):
                try:
                    candidates.extend(
                        format_candidate(row, source)
                        for row in search(query=match.group(1), limit=10).get("items", [])
                    )
                except Exception:
                    LOGGER.debug("Relaxed catalog search unavailable", exc_info=True)
    candidates = enrich_supplier_references(candidates)
    candidates.sort(key=lambda c: model_key(c["mfr_part_number"]) != target)
    return candidates[:max_candidates]


def fast_path_lcsc_lookup(
    c_codes: List[str],
    observed_tokens: Optional[List[str]] = None,
    target_mpn: Optional[str] = None,
    source_label: str = "原文",
    candidates=None,
) -> Optional[Dict[str, Any]]:
    """Common fast-path verification for authoritative LCSC C-codes."""
    valid_codes = [c for c in c_codes if re.fullmatch(r"C?\d{3,10}", str(c), re.I)]
    code_candidates = lookup_lcsc_candidates(valid_codes) if candidates is None else candidates

    if len(valid_codes) == len(code_candidates) == 1:
        candidate = code_candidates[0]
        # Check against observed tokens or target MPN
        matches_observed = True
        if observed_tokens:
            matches_observed = all(
                model_key(token) == model_key(candidate["mfr_part_number"])
                for token in observed_tokens
            )
        if target_mpn:
            cand_mpn = candidate.get("mfr_part_number") or ""
            matches_observed = matches_observed and (
                not target_mpn or model_key(target_mpn) == model_key(cand_mpn)
            )

        if matches_observed:
            return {
                "status": "success",
                "route": "direct_lcsc_match",
                "decision": "exact_match",
                "selected_component": candidate,
                "candidate_components": [],
                "reasoning": f"{source_label}立创编号 {valid_codes[0]} 与型号无冲突。",
            }

    return None


def lookup_lcsc_candidates(codes):
    candidates = []
    for code in dict.fromkeys(codes):
        if not re.fullmatch(r"C?\d{3,10}", str(code), re.I):
            continue
        numeric = int(str(code).lstrip("Cc"))
        try:
            item = lib_svc.get_jlcparts_component(numeric)
            if item and str(item.get("lcsc")) == str(numeric):
                candidates.append(format_candidate(item, "jlcparts"))
        except Exception:
            LOGGER.warning("Exact supplier lookup failed for %s", code, exc_info=True)
        if len(candidates) >= 8:
            break
    return candidates
