"""
External Library Service for PartShelf.
Connects to the three independent external component databases:
- Altium JLCPCB Libraries (altium_library.db)
- KiCad Symbols (kicad_symbols.db)
- JLCParts Database (jlcparts.db)

Ensures databases are available upon startup, handles auto-import if missing,
and provides unified, zero-data-loss querying capabilities.
"""

import os
import math
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.i18n.category_i18n import category_i18n

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "libraries"
SCRIPTS_DIR = BASE_DIR / "scripts"

ALTIUM_DB_PATH = DATA_DIR / "altium_library.db"
KICAD_DB_PATH = DATA_DIR / "kicad_symbols.db"
JLCPARTS_DB_PATH = DATA_DIR / "jlcparts.db"


def ensure_libraries_on_startup() -> Dict[str, Any]:
    """
    Called when PartShelf application starts up.
    Verifies that all three library databases are present.
    If any database is missing, runs the converter/importer script to import it.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    status = {}

    # 1. Altium
    if not ALTIUM_DB_PATH.exists():
        print("[Startup] Altium database not found. Running convert_altium...")
        try:
            from scripts.convert_altium import convert_altium
            count = convert_altium(output_db=ALTIUM_DB_PATH)
            status["altium"] = {"imported": True, "count": count}
        except Exception as e:
            print(f"[Startup] Error auto-importing Altium library: {e}")
            status["altium"] = {"imported": False, "error": str(e)}
    else:
        status["altium"] = {"imported": False, "exists": True}

    # 2. KiCad
    if not KICAD_DB_PATH.exists():
        print("[Startup] KiCad database not found. Running convert_kicad...")
        try:
            from scripts.convert_kicad import convert_kicad
            count = convert_kicad(output_db=KICAD_DB_PATH)
            status["kicad"] = {"imported": True, "count": count}
        except Exception as e:
            print(f"[Startup] Error auto-importing KiCad symbols: {e}")
            status["kicad"] = {"imported": False, "error": str(e)}
    else:
        status["kicad"] = {"imported": False, "exists": True}

    # 3. JLCParts
    if not JLCPARTS_DB_PATH.exists():
        print("[Startup] JLCParts database not found. Running import_jlcparts...")
        try:
            from scripts.import_jlcparts import import_jlcparts
            count = import_jlcparts(output_db=JLCPARTS_DB_PATH)
            status["jlcparts"] = {"imported": True, "count": count}
        except Exception as e:
            print(f"[Startup] Error auto-importing JLCParts: {e}")
            status["jlcparts"] = {"imported": False, "error": str(e)}
    else:
        status["jlcparts"] = {"imported": False, "exists": True}

    return status


def get_connection(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_libraries_status() -> Dict[str, Any]:
    """Returns availability and statistics for all three libraries."""
    result = {
        "altium": {"available": False, "count": 0},
        "kicad": {"available": False, "count": 0},
        "jlcparts": {"available": False, "count": 0, "lcsc_count": 0}
    }

    # Altium
    conn = get_connection(ALTIUM_DB_PATH)
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM altium_components")
            result["altium"]["count"] = cur.fetchone()[0]
            result["altium"]["available"] = True
            result["altium"]["size_bytes"] = ALTIUM_DB_PATH.stat().st_size
        except Exception:
            pass
        finally:
            conn.close()

    # KiCad
    conn = get_connection(KICAD_DB_PATH)
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM kicad_symbols")
            result["kicad"]["count"] = cur.fetchone()[0]
            result["kicad"]["available"] = True
            result["kicad"]["size_bytes"] = KICAD_DB_PATH.stat().st_size
        except Exception:
            pass
        finally:
            conn.close()

    # JLCParts
    conn = get_connection(JLCPARTS_DB_PATH)
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM jlc_components")
            result["jlcparts"]["count"] = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM lcsc_components")
            result["jlcparts"]["lcsc_count"] = cur.fetchone()[0]
            result["jlcparts"]["available"] = True
            result["jlcparts"]["size_bytes"] = JLCPARTS_DB_PATH.stat().st_size
        except Exception:
            pass
        finally:
            conn.close()

    return result


# ==========================================
# 1. Altium JLCPCB Libraries
# ==========================================

def get_altium_categories(lang: str = "zh") -> List[Dict[str, str]]:
    conn = get_connection(ALTIUM_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM altium_components WHERE category != '' ORDER BY category")
        return [
            {"category": r[0], "category_localized": category_i18n.translate_altium(r[0], lang)}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def get_altium_packages() -> List[str]:
    conn = get_connection(ALTIUM_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT package FROM altium_components WHERE package != '' ORDER BY package LIMIT 200")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def search_altium(
    query: str = "",
    category: Optional[str] = None,
    package: Optional[str] = None,
    basic_only: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
    limit: Optional[int] = None,
    lang: str = "zh"
) -> Dict[str, Any]:
    conn = get_connection(ALTIUM_DB_PATH)
    if not conn:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    if limit is not None:
        page_size = limit

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size

    cur = conn.cursor()
    conditions = []
    params = []

    q = (query or "").strip()
    if q:
        conditions.append("(lib_reference LIKE ? OR lcsc_part LIKE ? OR mfr_part_number LIKE ? OR description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

    if category:
        conditions.append("category = ?")
        params.append(category)

    if package:
        conditions.append("package = ?")
        params.append(package)

    if basic_only is True:
        conditions.append("basic_part = 1")
    elif basic_only is False:
        conditions.append("basic_part = 0")

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count
    cur.execute(f"SELECT count(*) FROM altium_components{where_sql}", params)
    total = cur.fetchone()[0]

    # Data
    sql = f"""
    SELECT id, lib_reference, lcsc_part, category, package, manufacturer,
           mfr_part_number, basic_part, description, resistance, capacitance,
           inductance, tolerance, voltage_rating, power_rating, datasheet_url,
           jlcpcb_url, lcsc_url, parameters_json, source_file
    FROM altium_components
    {where_sql}
    ORDER BY id
    LIMIT ? OFFSET ?
    """
    cur.execute(sql, params + [page_size, offset])
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        r["category_localized"] = category_i18n.translate_altium(r.get("category") or "", lang)
        if r.get("parameters_json"):
            try:
                r["parameters"] = json.loads(r["parameters_json"])
            except Exception:
                r["parameters"] = {}
        else:
            r["parameters"] = {}

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


def get_altium_component(comp_id: int, lang: str = "zh") -> Optional[Dict[str, Any]]:
    conn = get_connection(ALTIUM_DB_PATH)
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM altium_components WHERE id = ?", (comp_id,))
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        item["category_localized"] = category_i18n.translate_altium(item.get("category") or "", lang)
        if item.get("parameters_json"):
            try:
                item["parameters"] = json.loads(item["parameters_json"])
            except Exception:
                item["parameters"] = {}
        else:
            item["parameters"] = {}

        if item.get("raw_data_json"):
            try:
                item["raw_data"] = json.loads(item["raw_data_json"])
            except Exception:
                item["raw_data"] = {}
        else:
            item["raw_data"] = None

        return item
    finally:
        conn.close()


# ==========================================
# 2. KiCad Symbol Libraries
# ==========================================

def get_kicad_libraries() -> List[str]:
    conn = get_connection(KICAD_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT library FROM kicad_symbols ORDER BY library")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def search_kicad(
    query: str = "",
    library: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    conn = get_connection(KICAD_DB_PATH)
    if not conn:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    if limit is not None:
        page_size = limit

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size

    cur = conn.cursor()
    conditions = []
    params = []

    q = (query or "").strip()
    if q:
        conditions.append("(name LIKE ? OR value LIKE ? OR keywords LIKE ? OR description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

    if library:
        conditions.append("library = ?")
        params.append(library)

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count
    cur.execute(f"SELECT count(*) FROM kicad_symbols{where_sql}", params)
    total = cur.fetchone()[0]

    # Data (omitting heavy raw_sexpr in list view for performance)
    sql = f"""
    SELECT id, library, name, extends, reference, value, footprint,
           datasheet, description, keywords, fp_filters, in_bom, on_board,
           properties_json, source_file
    FROM kicad_symbols
    {where_sql}
    ORDER BY library, name
    LIMIT ? OFFSET ?
    """
    cur.execute(sql, params + [page_size, offset])
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        if r.get("properties_json"):
            try:
                r["properties"] = json.loads(r["properties_json"])
            except Exception:
                r["properties"] = {}
        else:
            r["properties"] = {}

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


def get_kicad_symbol(symbol_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection(KICAD_DB_PATH)
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM kicad_symbols WHERE id = ?", (symbol_id,))
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        if item.get("properties_json"):
            try:
                item["properties"] = json.loads(item["properties_json"])
            except Exception:
                item["properties"] = {}
        else:
            item["properties"] = {}
        return item
    finally:
        conn.close()


# ==========================================
# 3. JLCParts Database
# ==========================================

def get_jlcparts_categories(lang: str = "zh") -> List[Dict[str, Any]]:
    conn = get_connection(JLCPARTS_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT category, subcategory, count(*) as cnt
            FROM jlc_components
            WHERE category != ''
            GROUP BY category, subcategory
            ORDER BY category, subcategory
        """)
        rows = cur.fetchall()
        result = {}
        for r in rows:
            cat = r["category"]
            subcat = r["subcategory"]
            cnt = r["cnt"]
            if cat not in result:
                result[cat] = {
                    "category": cat,
                    "category_localized": category_i18n.translate_primary(cat, lang),
                    "subcategories": []
                }
            if subcat:
                result[cat]["subcategories"].append({
                    "subcategory": subcat,
                    "subcategory_localized": category_i18n.translate_secondary(subcat, lang),
                    "count": cnt
                })
        return list(result.values())
    finally:
        conn.close()


def parse_jlcparts_prices(price_str: Optional[str]) -> List[Dict[str, Any]]:
    if not price_str:
        return []
    breaks = []
    # format: "1-9:1.5179,10-11:1.5179,12-199:1.5179,200-499:0.6069,500-999:0.5857,1000-:0.576"
    for part in price_str.split(","):
        part = part.strip()
        if ":" in part:
            qty_range, unit_price = part.split(":", 1)
            breaks.append({"range": qty_range.strip(), "price": unit_price.strip()})
    return breaks


def search_jlcparts(
    query: str = "",
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    package: Optional[str] = None,
    library_type: Optional[str] = None,
    in_stock_only: bool = False,
    page: int = 1,
    page_size: int = 50,
    limit: Optional[int] = None,
    lang: str = "zh"
) -> Dict[str, Any]:
    conn = get_connection(JLCPARTS_DB_PATH)
    if not conn:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    if limit is not None:
        page_size = limit

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size

    cur = conn.cursor()
    conditions = []
    params = []

    q = (query or "").strip()
    if q:
        # Check if user entered LCSC code e.g. "C12345" or "12345"
        if q.upper().startswith("C") and q[1:].isdigit():
            lcsc_num = int(q[1:])
            conditions.append("(j.lcsc = ? OR j.mfr LIKE ?)")
            params.extend([lcsc_num, f"%{q}%"])
        elif q.isdigit():
            lcsc_num = int(q)
            conditions.append("(j.lcsc = ? OR j.mfr LIKE ?)")
            params.extend([lcsc_num, f"%{q}%"])
        else:
            conditions.append("(j.mfr LIKE ? OR ('C' || j.lcsc) LIKE ? OR j.description LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    if category:
        conditions.append("j.category = ?")
        params.append(category)

    if subcategory:
        conditions.append("j.subcategory = ?")
        params.append(subcategory)

    if package:
        conditions.append("j.package = ?")
        params.append(package)

    if library_type:
        conditions.append("j.library_type = ?")
        params.append(library_type)

    if in_stock_only:
        conditions.append("j.stock > 0")

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count
    cur.execute(f"SELECT count(*) FROM jlc_components j{where_sql}", params)
    total = cur.fetchone()[0]

    # Data
    sql = f"""
    SELECT j.lcsc, j.category, j.subcategory, j.mfr, j.package, j.joints,
           j.manufacturer, j.library_type, j.preferred, j.stock, j.price,
           j.description, j.datasheet, j.attributes, j.rohs, l.image, l.url_slug
    FROM jlc_components j
    LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
    {where_sql}
    ORDER BY j.stock DESC, j.preferred DESC
    LIMIT ? OFFSET ?
    """
    cur.execute(sql, params + [page_size, offset])
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        r["category_localized"] = category_i18n.translate_primary(r.get("category") or "", lang)
        r["subcategory_localized"] = category_i18n.translate_secondary(r.get("subcategory") or "", lang)
        # Build image URLs
        if r.get("image"):
            r["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{r['image']}"
            r["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{r['image']}"
            r["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{r['image']}"
        else:
            r["image_url_small"] = None
            r["image_url_medium"] = None
            r["image_url_large"] = None

        if r.get("attributes"):
            try:
                r["attributes_dict"] = json.loads(r["attributes"])
            except Exception:
                r["attributes_dict"] = {}
        else:
            r["attributes_dict"] = {}

        r["price_breaks"] = parse_jlcparts_prices(r.get("price"))

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


def get_jlcparts_component(lcsc: int, lang: str = "zh") -> Optional[Dict[str, Any]]:
    conn = get_connection(JLCPARTS_DB_PATH)
    if not conn:
        return None
    try:
        cur = conn.cursor()
        sql = """
        SELECT j.*, l.image, l.url_slug
        FROM jlc_components j
        LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
        WHERE j.lcsc = ?
        """
        cur.execute(sql, (lcsc,))
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        item["category_localized"] = category_i18n.translate_primary(item.get("category") or "", lang)
        item["subcategory_localized"] = category_i18n.translate_secondary(item.get("subcategory") or "", lang)

        if item.get("image"):
            item["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{item['image']}"
            item["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{item['image']}"
            item["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{item['image']}"
        else:
            item["image_url_small"] = None
            item["image_url_medium"] = None
            item["image_url_large"] = None

        if item.get("attributes"):
            try:
                item["attributes_dict"] = json.loads(item["attributes"])
            except Exception:
                item["attributes_dict"] = {}
        else:
            item["attributes_dict"] = {}

        if item.get("attrition"):
            try:
                item["attrition_dict"] = json.loads(item["attrition"])
            except Exception:
                item["attrition_dict"] = {}
        else:
            item["attrition_dict"] = {}

        item["price_breaks"] = parse_jlcparts_prices(item.get("price"))
        if item.get("url_slug"):
            item["lcsc_url"] = f"https://www.lcsc.com/product-detail/{item['url_slug']}_C{item['lcsc']}.html"
        else:
            item["lcsc_url"] = f"https://www.lcsc.com/search?q=C{item['lcsc']}"

        return item
    finally:
        conn.close()


def search_all_libraries(query: str, limit_each: int = 20, lang: str = "zh") -> Dict[str, Any]:
    """Unified cross-library search across Altium, KiCad, and JLCParts."""
    return {
        "query": query,
        "altium": search_altium(query, page_size=limit_each, lang=lang).get("items", []),
        "kicad": search_kicad(query, page_size=limit_each).get("items", []),
        "jlcparts": search_jlcparts(query, page_size=limit_each, lang=lang).get("items", []),
    }


# ==========================================
# Dynamic Hydration Helpers for PartShelf
# ==========================================

_PART_SUMMARY_CACHE: Dict[str, Dict[str, Any]] = {}


def resolve_part_summary(library_source: str, external_part_id: str, lang: str = "zh") -> Dict[str, Any]:
    """
    Dynamically resolves common component attributes (name, manufacturer, package, type, etc.)
    from the referenced external database with in-memory caching.
    """
    cache_key = f"{lang}:{library_source}:{external_part_id}"
    if cache_key in _PART_SUMMARY_CACHE:
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

    src = (library_source or "").lower()
    pid_str = str(external_part_id)

    if src == "altium":
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

    elif src == "jlcparts":
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

    if src == "altium":
        comp_id = int(pid_str) if pid_str.isdigit() else 0
        external_details = get_altium_component(comp_id, lang)
    elif src == "kicad":
        sym_id = int(pid_str) if pid_str.isdigit() else 0
        external_details = get_kicad_symbol(sym_id)
    elif src == "jlcparts":
        lcsc_num = int(pid_str.replace("C", "")) if pid_str.replace("C", "").isdigit() else 0
        external_details = get_jlcparts_component(lcsc_num, lang)

    return {
        "summary": summary,
        "external_details": external_details
    }
