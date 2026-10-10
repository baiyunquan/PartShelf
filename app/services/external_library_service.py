"""External Library Service for PartShelf (Facade & Orchestrator).

Provides unified, zero-data-loss access across all four component databases:
- JLCParts Database (jlcparts.db)
- Altium JLCPCB Libraries (altium_library.db)
- KiCad Symbols (kicad_symbols.db)
- Fasteners and Mechanical Standards (fasteners.db)

Maintains full backward compatibility for all function signatures and DB paths.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services import component_search_service
from app.services.libraries import (
    ALTIUM_DB_PATH,
    BASE_DIR,
    DATA_DIR,
    FASTENER_DOMAINS,
    FASTENERS_DB_PATH,
    JLCPARTS_DB_PATH,
    KICAD_DB_PATH,
    SCRIPTS_DIR,
    STATIC_PARTS_DIR,
    AltiumLibrary,
    FastenersLibrary,
    JLCPartsLibrary,
    KiCadLibrary,
    altium_library,
    ensure_libraries_on_startup,
    fasteners_library,
    get_connection,
    get_libraries_status,
    jlcparts_library,
    kicad_library,
)
from app.services.libraries.common import (
    _custom_length_from_row_key,
    _custom_nominal_from_row_key,
    _custom_row_key,
    _normalize_custom_nominal,
)

# -------------------------------------------------------------
# Functional API Delegation to Class Singletons
# -------------------------------------------------------------

# Altium
get_altium_categories = altium_library.get_categories
get_altium_packages = altium_library.get_packages
search_altium = altium_library.search
get_altium_component = altium_library.get_component

# KiCad
get_kicad_libraries = kicad_library.get_libraries
search_kicad = kicad_library.search
get_kicad_symbol = kicad_library.get_symbol

# JLCParts
get_jlcparts_categories = jlcparts_library.get_categories
parse_jlcparts_prices = jlcparts_library.parse_prices
extract_jlcparts_specs = jlcparts_library.extract_specs
search_jlcparts = jlcparts_library.search
get_jlcparts_component = jlcparts_library.get_component

# Fasteners
get_fastener_domains = fasteners_library.get_domains
get_fastener_categories = fasteners_library.get_categories
get_fastener_authorities = fasteners_library.get_authorities
get_fastener_metadata = fasteners_library.get_metadata
query_fasteners = fasteners_library.query
get_fastener_detail = fasteners_library.get_detail
append_fastener_spec = fasteners_library.append_spec
get_fastener_hole_charts = fasteners_library.get_hole_charts
get_fastener_assembly_guides = fasteners_library.get_assembly_guides

# -------------------------------------------------------------
# Cross-Library Search & Dynamic Hydration Resolvers
# -------------------------------------------------------------

def search_all_libraries(query: str, limit_each: int = 20, lang: str = "zh") -> Dict[str, Any]:
    """Unified cross-library search across JLCParts, Altium, and KiCad."""
    return {
        "query": query,
        "jlcparts": search_jlcparts(query, page_size=limit_each, lang=lang).get("items", []),
        "altium": search_altium(query, page_size=limit_each, lang=lang).get("items", []),
        "kicad": search_kicad(query, page_size=limit_each).get("items", []),
    }


_PART_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}


def resolve_part_summary(library_source: str, external_part_id: str, lang: str = "zh") -> Dict[str, Any]:
    """
    Dynamically resolves common component attributes (name, manufacturer, package, type, etc.)
    from the referenced external database with in-memory caching.
    """
    src = (library_source or "").lower()
    cache_key = f"{lang}:{src}:{external_part_id}"
    if src != "custom" and cache_key in _PART_SUMMARY_CACHE:
        return _PART_SUMMARY_CACHE[cache_key]

    summary = {
        "name": f"Part #{external_part_id}",
        "manufacturer": "Unknown",
        "package": "Standard",
        "part_type": "General",
        "description": "",
        "image_url": None,
        "datasheet_url": None,
    }

    pid_str = str(external_part_id)

    if src == "jlcparts":
        lcsc_num = int(pid_str.replace("C", "")) if pid_str.replace("C", "").isdigit() else 0
        jlc = get_jlcparts_component(lcsc_num, lang)
        if jlc:
            summary["name"] = jlc.get("mfr") or f"C{jlc.get('lcsc')}"
            summary["manufacturer"] = jlc.get("manufacturer") or "Unknown"
            summary["package"] = jlc.get("package") or "Standard"
            cat_str = jlc.get("category") or ""
            sub_str = jlc.get("subcategory") or ""
            cat_trans = jlc.get("category_localized") or cat_str
            sub_trans = jlc.get("subcategory_localized") or sub_str
            if cat_trans and sub_trans:
                summary["part_type"] = f"{cat_trans} / {sub_trans}"
            else:
                summary["part_type"] = cat_trans or sub_trans or cat_str or "General"
            summary["part_type_localized"] = summary["part_type"]
            summary["part_type_en"] = f"{cat_str} / {sub_str}" if (cat_str and sub_str) else (cat_str or "General")
            summary["description"] = jlc.get("description") or ""
            summary["image_url"] = jlc.get("image_url_small") or None
            summary["datasheet_url"] = jlc.get("datasheet") or None

    elif src == "altium":
        comp_id = int(pid_str) if pid_str.isdigit() else 0
        comp = get_altium_component(comp_id, lang)
        if comp:
            summary["name"] = comp.get("lib_reference") or comp.get("mfr_part_number") or f"Altium #{comp_id}"
            summary["manufacturer"] = comp.get("manufacturer") or "Generic"
            summary["package"] = comp.get("package") or "Standard"
            raw_cat = comp.get("category") or "General"
            summary["part_type"] = comp.get("category_localized") or raw_cat
            summary["part_type_localized"] = summary["part_type"]
            summary["part_type_en"] = raw_cat
            summary["description"] = comp.get("description") or ""
            summary["datasheet_url"] = comp.get("datasheet_url") or None

    elif src == "kicad":
        sym_id = int(pid_str) if pid_str.isdigit() else 0
        sym = get_kicad_symbol(sym_id)
        if sym:
            summary["name"] = sym.get("value") or sym.get("name") or f"KiCad #{sym_id}"
            summary["manufacturer"] = sym.get("properties", {}).get("Manufacturer") or "Generic"
            summary["package"] = sym.get("footprint") or "Symbol"
            summary["part_type"] = sym.get("library") or "General"
            summary["part_type_localized"] = summary["part_type"]
            summary["part_type_en"] = summary["part_type"]
            summary["description"] = sym.get("description") or sym.get("keywords") or ""
            summary["datasheet_url"] = sym.get("datasheet") if sym.get("datasheet") != "~" else None

    elif src == "fasteners":
        from app.services.fastener_variant_service import get_fastener_variant
        variant = get_fastener_variant(pid_str)
        if variant:
            summary.update(variant["summary"])
            summary["part_type_localized"] = summary["part_type"]
            summary["part_type_en"] = variant["standard"].get("category_group") or summary["part_type"]

    elif src == "custom":
        custom_id = int(pid_str) if pid_str.isdigit() else 0
        from db.database import SessionLocal
        from app.models.custom_component import CustomComponent
        db = SessionLocal()
        try:
            custom = db.query(CustomComponent).filter(CustomComponent.id == custom_id).first()
            if custom:
                summary["name"] = custom.name or f"Custom #{custom_id}"
                summary["manufacturer"] = custom.manufacturer or "Custom"
                summary["package"] = custom.package or "Custom"
                summary["part_type"] = custom.part_type or "Custom"
                summary["part_type_localized"] = summary["part_type"]
                summary["part_type_en"] = summary["part_type"]
                summary["description"] = custom.description or ""
        finally:
            db.close()

    if src != "custom":
        _PART_SUMMARY_CACHE[cache_key] = summary
    return summary


def resolve_part_full(library_source: str, external_part_id: str, lang: str = "zh") -> Dict[str, Any]:
    """
    Returns full external component details (including technical attributes or raw S-expressions)
    along with standard summary properties.
    """
    summary = resolve_part_summary(library_source, external_part_id, lang)
    external_details = None

    src = (library_source or "").lower()
    pid_str = str(external_part_id)

    if src == "jlcparts":
        lcsc_num = int(pid_str.replace("C", "")) if pid_str.replace("C", "").isdigit() else 0
        external_details = get_jlcparts_component(lcsc_num, lang)
    elif src == "altium":
        comp_id = int(pid_str) if pid_str.isdigit() else 0
        external_details = get_altium_component(comp_id, lang)
    elif src == "kicad":
        sym_id = int(pid_str) if pid_str.isdigit() else 0
        external_details = get_kicad_symbol(sym_id)
    elif src == "fasteners":
        from app.services.fastener_variant_service import get_fastener_variant
        external_details = get_fastener_variant(pid_str)
    elif src == "custom":
        custom_id = int(pid_str) if pid_str.isdigit() else 0
        from db.database import SessionLocal
        from app.models.custom_component import CustomComponent
        db = SessionLocal()
        try:
            custom = db.query(CustomComponent).filter(CustomComponent.id == custom_id).first()
            if custom:
                specs_dict = None
                if custom.specs:
                    try:
                        import json
                        specs_dict = json.loads(custom.specs)
                    except Exception:
                        specs_dict = {"raw": custom.specs}
                external_details = {
                    "id": custom.id,
                    "name": custom.name,
                    "manufacturer": custom.manufacturer,
                    "package": custom.package,
                    "part_type": custom.part_type,
                    "description": custom.description,
                    "specs": specs_dict,
                    "raw_ocr_text": custom.raw_ocr_text,
                    "source_scan_id": custom.source_scan_id,
                    "created_at": str(custom.created_at) if custom.created_at else None,
                }
        finally:
            db.close()

    return {
        "summary": summary,
        "external_details": external_details
    }
