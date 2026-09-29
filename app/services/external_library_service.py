"""
External Library Service for PartShelf.
Connects to the three independent external component databases:
- JLCParts Database (jlcparts.db)
- Altium JLCPCB Libraries (altium_library.db)
- KiCad Symbols (kicad_symbols.db)

Ensures databases are available upon startup, handles auto-import if missing,
and provides unified, zero-data-loss querying capabilities.
"""

import os
import math
import sqlite3
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.i18n.category_i18n import category_i18n

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "libraries"
SCRIPTS_DIR = BASE_DIR / "scripts"

JLCPARTS_DB_PATH = DATA_DIR / "jlcparts.db"
ALTIUM_DB_PATH = DATA_DIR / "altium_library.db"
KICAD_DB_PATH = DATA_DIR / "kicad_symbols.db"
FASTENERS_DB_PATH = DATA_DIR / "fasteners.db"
STATIC_PARTS_DIR = BASE_DIR / "static" / "images" / "parts"


def ensure_libraries_on_startup() -> Dict[str, Any]:
    """
    Called when PartShelf application starts up.
    Verifies that all three library databases are present.
    If any database is missing, runs the converter/importer script to import it.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    status = {}

    # 1. JLCParts
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

    # 2. Altium
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

    # 3. KiCad
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

    # 4. Fasteners
    if not FASTENERS_DB_PATH.exists():
        print("[Startup] Fasteners database not found. Running import_fasteners...")
        try:
            from scripts.import_fasteners import import_fasteners
            res = import_fasteners(output_db=FASTENERS_DB_PATH)
            status["fasteners"] = {"imported": True, "count": res["standards"]}
        except Exception as e:
            print(f"[Startup] Error auto-importing Fasteners: {e}")
            status["fasteners"] = {"imported": False, "error": str(e)}
    else:
        status["fasteners"] = {"imported": False, "exists": True}

    return status


def get_connection(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_libraries_status() -> Dict[str, Any]:
    """Returns availability and statistics for all four libraries."""
    result = {
        "jlcparts": {"available": False, "count": 0, "lcsc_count": 0},
        "altium": {"available": False, "count": 0},
        "kicad": {"available": False, "count": 0},
        "fasteners": {"available": False, "count": 0, "tables_count": 0}
    }

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

    # Fasteners
    conn = get_connection(FASTENERS_DB_PATH)
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM fastener_standards")
            result["fasteners"]["count"] = cur.fetchone()[0]
            cur.execute("SELECT count(DISTINCT table_name) FROM fastener_tables")
            result["fasteners"]["tables_count"] = cur.fetchone()[0]
            result["fasteners"]["available"] = True
            result["fasteners"]["size_bytes"] = FASTENERS_DB_PATH.stat().st_size
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


def extract_jlcparts_specs(category: str, subcategory: str, attrs_dict: Dict[str, Any], description: Optional[str] = "") -> str:
    """
    Extracts up to 3 most important technical parameters (e.g. Capacitance, Tolerance, Voltage)
    for JLCPCB/LCSC components based on component category.
    """
    if not attrs_dict and not description:
        return "-"

    cat_lower = f"{category or ''} {subcategory or ''}".lower()
    specs = []

    # 1. Targeted priority attributes by category
    if "capacitor" in cat_lower:
        for k in ["Capacitance", "Tolerance", "Voltage Rating"]:
            if attrs_dict.get(k):
                specs.append(str(attrs_dict[k]))
    elif "resistor" in cat_lower:
        for k in ["Resistance", "Tolerance", "Power(Watts)"]:
            if attrs_dict.get(k):
                specs.append(str(attrs_dict[k]))
    elif "inductor" in cat_lower or "choke" in cat_lower:
        for k in ["Inductance", "Tolerance", "Current Rating", "DC Resistance(DCR)"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))
    elif "diode" in cat_lower:
        for k in ["Zener Voltage(Range)", "Forward Voltage (Vf)", "Current - Average Rectified (Io)", "Pd - Power Dissipation"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))
    elif "mosfet" in cat_lower or "transistor" in cat_lower or "bjt" in cat_lower:
        for k in ["Drain to Source Voltage", "Collector - Emitter Voltage VCEO", "Current - Continuous Drain(Id)", "Current - Collector(Ic)", "RDS(on)", "type"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))
    elif "crystal" in cat_lower or "oscillator" in cat_lower:
        for k in ["Frequency", "Frequency Tolerance", "Load Capacitance"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))
    elif "fuse" in cat_lower:
        for k in ["Current Rating", "Voltage Rating", "Response Time"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))
    elif "led" in cat_lower:
        for k in ["Emitted Color", "Dominant Wavelength", "Forward Voltage (Vf)"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))
    elif "linear" in cat_lower or "ldo" in cat_lower or "pmic" in cat_lower:
        for k in ["Output Voltage", "Output Current", "Input Voltage"]:
            if attrs_dict.get(k) and len(specs) < 3:
                specs.append(str(attrs_dict[k]))

    # 2. If priority mappings didn't get 3, check generic important keys
    if len(specs) < 3:
        generic_keys = [
            "Capacitance", "Resistance", "Inductance", "Voltage Rating", "Tolerance", 
            "Power(Watts)", "Current Rating", "Frequency", "Operating Temperature", "Type"
        ]
        for k in generic_keys:
            if k in attrs_dict and str(attrs_dict[k]) not in specs:
                specs.append(str(attrs_dict[k]))
                if len(specs) >= 3:
                    break

    # 3. Fallback to remaining non-boilerplate attributes
    if len(specs) < 3:
        for k, v in attrs_dict.items():
            val_str = str(v)
            if k not in ["RoHS", "Package", "Lifecycle Status"] and val_str not in specs and len(val_str) < 30:
                specs.append(val_str)
                if len(specs) >= 3:
                    break

    if specs:
        return ", ".join(specs[:3])
    return (description[:35] + "...") if description and len(description) > 35 else (description or "-")


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
    params = {}
    code_query = False

    q = (query or "").strip()
    capacitance = None
    capacitance_sql = (
        "CASE WHEN j.attributes LIKE :capacitance_hint AND json_valid(j.attributes) THEN "
        "lower(replace(replace(replace(json_extract(j.attributes, '$.Capacitance'), "
        "' ', ''), 'µ', 'u'), 'μ', 'u')) END"
    )
    if q:
        params.update(query_lower=q.lower(), like=f"%{q}%", prefix=f"{q}%", code=None)
        capacitance_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([pnumµμ]?)f", q, re.IGNORECASE)
        if capacitance_match:
            unit = capacitance_match.group(2).lower().replace("µ", "u").replace("μ", "u")
            capacitance = f"{capacitance_match.group(1)}{unit}f"
            params.update(
                capacitance=capacitance,
                query_lower=capacitance,
                like=f"%{capacitance}%",
                prefix=f"{capacitance}%",
            )
            unit_hint = "" if unit == "u" else unit
            params["capacitance_hint"] = f"%{capacitance_match.group(1)}%{unit_hint}f%"

        # Check if user entered LCSC code e.g. "C12345" or "12345"
        if q.upper().startswith("C") and q[1:].isdigit():
            params["code"] = int(q[1:])
            code_query = True
        elif q.isdigit():
            params["code"] = int(q)
            code_query = True
        else:
            matches = ["j.mfr LIKE :like", "('C' || j.lcsc) LIKE :like", "j.description LIKE :like"]
            if capacitance is not None:
                matches.append(f"{capacitance_sql} = :capacitance")
            conditions.append("(" + " OR ".join(matches) + ")")

    if category:
        conditions.append("j.category = :category")
        params["category"] = category

    if subcategory:
        conditions.append("j.subcategory = :subcategory")
        params["subcategory"] = subcategory

    if package:
        conditions.append("j.package = :package")
        params["package"] = package

    if library_type:
        conditions.append("j.library_type = :library_type")
        params["library_type"] = library_type

    if in_stock_only:
        conditions.append("j.stock > 0")

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    if code_query:
        # The model index covers the broad code search; fetch full rows only
        # for matching IDs instead of scanning every large component record.
        hits_sql = """
            hits AS (
                SELECT lcsc FROM jlc_components WHERE mfr LIKE :like
                UNION
                SELECT lcsc FROM jlc_components WHERE lcsc = :code
            )
        """
        candidate_from = "FROM hits h JOIN jlc_components j ON j.lcsc = h.lcsc"
    else:
        hits_sql = ""
        candidate_from = "FROM jlc_components j"

    if q:
        rank = ["WHEN j.lcsc = :code OR lower(j.mfr) = :query_lower THEN 0"]
        if capacitance is not None:
            rank.append(f"WHEN {capacitance_sql} = :capacitance THEN 1")
        rank.extend([
            "WHEN lower(j.mfr) LIKE lower(:prefix) THEN 2",
            "WHEN lower(j.mfr) LIKE lower(:like) THEN 3",
        ])
        rank_sql = "CASE " + " ".join(rank) + " ELSE 4 END"
    else:
        # Preserve the stock-first listing when there is no search term.
        cur.execute(f"SELECT count(*) FROM jlc_components j{where_sql}", params)
        total = cur.fetchone()[0]

    row_columns = """
        j.lcsc, j.category, j.subcategory, j.mfr, j.package, j.joints,
        j.manufacturer, j.library_type, j.preferred, j.stock, j.price,
        j.description, j.datasheet, j.attributes, j.rohs, l.image, l.url_slug
    """
    if q:
        # Rank and paginate narrow rows before loading attributes and joined data.
        ranked_prefix = f"{hits_sql}, " if code_query else ""
        sql = f"""
        WITH {ranked_prefix} ranked AS (
            SELECT j.lcsc, j.stock, j.preferred, {rank_sql} AS relevance,
                   count(*) OVER() AS search_total
            {candidate_from}
            {where_sql}
            ORDER BY relevance, j.stock DESC, j.preferred DESC, j.lcsc ASC
            LIMIT :page_size OFFSET :offset
        )
        SELECT {row_columns}, ranked.search_total
        FROM ranked
        JOIN jlc_components j ON j.lcsc = ranked.lcsc
        LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
        ORDER BY ranked.relevance, ranked.stock DESC,
                 ranked.preferred DESC, ranked.lcsc ASC
        """
    else:
        sql = f"""
        SELECT {row_columns}
        FROM jlc_components j
        LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
        {where_sql}
        ORDER BY j.stock DESC, j.preferred DESC, j.lcsc ASC
        LIMIT :page_size OFFSET :offset
        """
    cur.execute(sql, {**params, "page_size": page_size, "offset": offset})
    rows = [dict(r) for r in cur.fetchall()]
    if q:
        if rows:
            total = rows[0]["search_total"]
            for row in rows:
                row.pop("search_total")
        else:
            # A page beyond the last match still reports the full match count.
            count_prefix = f"WITH {hits_sql}" if code_query else ""
            cur.execute(f"{count_prefix} SELECT count(*) {candidate_from}{where_sql}", params)
            total = cur.fetchone()[0]
    conn.close()

    for r in rows:
        r["category_localized"] = category_i18n.translate_primary(r.get("category") or "", lang)
        r["subcategory_localized"] = category_i18n.translate_secondary(r.get("subcategory") or "", lang)
        # Build image URLs
        if r.get("image"):
            img_file = r["image"]
            if (STATIC_PARTS_DIR / img_file).exists():
                r["image_url_small"] = f"/static/images/parts/{img_file}"
                r["image_url_medium"] = f"/static/images/parts/{img_file}"
            else:
                r["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{img_file}"
                r["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{img_file}"
            r["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{img_file}"
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

        r["specs"] = extract_jlcparts_specs(
            r.get("category") or "",
            r.get("subcategory") or "",
            r.get("attributes_dict") or {},
            r.get("description")
        )

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
            img_file = item["image"]
            if (STATIC_PARTS_DIR / img_file).exists():
                item["image_url_small"] = f"/static/images/parts/{img_file}"
                item["image_url_medium"] = f"/static/images/parts/{img_file}"
            else:
                item["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{img_file}"
                item["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{img_file}"
            item["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{img_file}"
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

        item["specs"] = extract_jlcparts_specs(
            item.get("category") or "",
            item.get("subcategory") or "",
            item.get("attributes_dict") or {},
            item.get("description")
        )

        item["price_breaks"] = parse_jlcparts_prices(item.get("price"))
        if item.get("url_slug"):
            item["lcsc_url"] = f"https://www.lcsc.com/product-detail/{item['url_slug']}_C{item['lcsc']}.html"
        else:
            item["lcsc_url"] = f"https://www.lcsc.com/search?q=C{item['lcsc']}"

        return item
    finally:
        conn.close()


def search_all_libraries(query: str, limit_each: int = 20, lang: str = "zh") -> Dict[str, Any]:
    """Unified cross-library search across JLCParts, Altium, and KiCad."""
    return {
        "query": query,
        "jlcparts": search_jlcparts(query, page_size=limit_each, lang=lang).get("items", []),
        "altium": search_altium(query, page_size=limit_each, lang=lang).get("items", []),
        "kicad": search_kicad(query, page_size=limit_each).get("items", []),
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
    elif src == "custom":
        custom_id = int(pid_str) if pid_str.isdigit() else 0
        from db.database import SessionLocal
        from app.models.custom_component import CustomComponent
        db = SessionLocal()
        try:
            custom = db.query(CustomComponent).filter(CustomComponent.id == custom_id).first()
            if custom:
                external_details = {
                    "id": custom.id,
                    "name": custom.name,
                    "manufacturer": custom.manufacturer,
                    "package": custom.package,
                    "part_type": custom.part_type,
                    "description": custom.description,
                    "created_at": str(custom.created_at) if custom.created_at else None,
                }
        finally:
            db.close()

    return {
        "summary": summary,
        "external_details": external_details
    }


# ==========================================
# 4. Mechanical & Structural Library (FreeCAD & Whole-Spec)
# ==========================================

FASTENER_DOMAINS = [
    {"domain": "fasteners", "name_zh": "紧固件", "name_en": "Fasteners"},
    {"domain": "power_transmission", "name_zh": "动力传动", "name_en": "Power Transmission"},
    {"domain": "structural_materials", "name_zh": "结构材料/型材", "name_en": "Structural Materials & Profiles"},
]


def get_fastener_domains() -> List[Dict[str, Any]]:
    """Returns domain groups (Fasteners, Power Transmission, Structural Materials) with counts."""
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT domain, count(*) as count FROM fastener_standards GROUP BY domain")
        counts = {row["domain"]: row["count"] for row in cur.fetchall()}
        res = []
        for d in FASTENER_DOMAINS:
            res.append({
                "domain": d["domain"],
                "name_zh": d["name_zh"],
                "name_en": d["name_en"],
                "count": counts.get(d["domain"], 0)
            })
        return res
    finally:
        conn.close()


def get_fastener_categories(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all category groups with counts from fasteners.db, optionally filtered by domain."""
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        if domain and domain != "all":
            cur.execute("""
                SELECT domain, category_group, category_group_zh, count(*) as count
                FROM fastener_standards
                WHERE domain = ?
                GROUP BY domain, category_group, category_group_zh
                ORDER BY count DESC
            """, (domain,))
        else:
            cur.execute("""
                SELECT domain, category_group, category_group_zh, count(*) as count
                FROM fastener_standards
                GROUP BY domain, category_group, category_group_zh
                ORDER BY domain ASC, count DESC
            """)
        return [
            {
                "domain": row["domain"],
                "group": row["category_group"],
                "group_zh": row["category_group_zh"],
                "count": row["count"]
            }
            for row in cur.fetchall()
        ]
    finally:
        conn.close()


def get_fastener_authorities() -> List[Dict[str, Any]]:
    """Returns all standard authorities (ISO, DIN, ASME, JIS, KS, etc.) with counts."""
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT authority, count(*) as count
            FROM fastener_standards
            GROUP BY authority
            ORDER BY count DESC
        """)
        return [
            {
                "authority": row["authority"],
                "count": row["count"]
            }
            for row in cur.fetchall()
        ]
    finally:
        conn.close()


def query_fasteners(
    page: int = 1,
    page_size: int = 25,
    query: Optional[str] = None,
    category: Optional[str] = None,
    authority: Optional[str] = None,
    domain: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search and page fastener / mechanical standards from fasteners.db.
    Supports filtering by domain (fasteners, power_transmission, structural_materials).
    """
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []

        if domain and domain != "all":
            where_clauses.append("domain = ?")
            params.append(domain)

        if query:
            q_clean = query.strip()
            q_param = f"%{q_clean}%"
            where_clauses.append("""(
                standard_code LIKE ?
                OR standard_name LIKE ?
                OR description LIKE ?
                OR category_group_zh LIKE ?
                OR param_table_name IN (SELECT DISTINCT table_name FROM fastener_tables WHERE row_key = ? OR row_key LIKE ?)
            )""")
            params.extend([q_param, q_param, q_param, q_param, q_clean, q_param])

        if category and category != "all":
            where_clauses.append("(category_group = ? OR category_group_zh = ?)")
            params.extend([category, category])

        if authority and authority != "all":
            where_clauses.append("authority = ?")
            params.append(authority)

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Total count
        cur.execute(f"SELECT count(*) FROM fastener_standards{where_sql}", params)
        total = cur.fetchone()[0]

        total_pages = math.ceil(total / page_size) if total > 0 else 1
        page = max(1, min(page, total_pages)) if total > 0 else 1
        offset = (page - 1) * page_size

        cur.execute(f"""
            SELECT id, standard_code, standard_name, authority, domain, category_group, category_group_zh,
                   description, param_table_name, length_table_name, has_length, source_file
            FROM fastener_standards
            {where_sql}
            ORDER BY domain ASC, authority ASC, standard_code ASC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])

        items = [dict(row) for row in cur.fetchall()]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
    finally:
        conn.close()


def get_fastener_detail(standard_code: str) -> Optional[Dict[str, Any]]:
    """
    Returns complete metadata, dimensional parameter matrix, valid length matrix,
    hole drill references, and torque/wrench assembly guidelines for a standard.
    """
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return None

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM fastener_standards
            WHERE standard_code = ? OR lower(standard_code) = lower(?)
            LIMIT 1
        """, (standard_code, standard_code))
        std_row = cur.fetchone()
        if not std_row:
            return None

        standard = dict(std_row)
        param_table = standard.get("param_table_name")
        length_table = standard.get("length_table_name")

        # 1. Fetch param table titles and data
        param_titles = []
        param_rows = []
        if param_table:
            cur.execute("SELECT titles_json FROM fastener_table_titles WHERE table_name = ?", (param_table,))
            t_row = cur.fetchone()
            if t_row:
                try:
                    param_titles = json.loads(t_row[0])
                except Exception:
                    param_titles = []

            cur.execute("SELECT row_key, data_json FROM fastener_tables WHERE table_name = ? ORDER BY id ASC", (param_table,))
            for r in cur.fetchall():
                try:
                    vals = json.loads(r["data_json"])
                except Exception:
                    vals = []
                param_rows.append({
                    "nominal": r["row_key"],
                    "values": vals
                })

        # 2. Fetch length table titles and data
        length_titles = []
        length_rows = []
        if length_table:
            cur.execute("SELECT titles_json FROM fastener_table_titles WHERE table_name = ?", (length_table,))
            lt_row = cur.fetchone()
            if lt_row:
                try:
                    length_titles = json.loads(lt_row[0])
                except Exception:
                    length_titles = []

            cur.execute("SELECT row_key, data_json FROM fastener_tables WHERE table_name = ? ORDER BY id ASC", (length_table,))
            for r in cur.fetchall():
                try:
                    vals = json.loads(r["data_json"])
                except Exception:
                    vals = []
                length_rows.append({
                    "key": r["row_key"],
                    "lengths": [str(x) for x in vals if str(x).strip()]
                })

        # 3. Fetch hole chart matching standard if metric
        cur.execute("SELECT nominal_dia, hole_diameter FROM fastener_hole_charts WHERE chart_type = 'metric_tap_hole'")
        tap_holes = {r[0]: r[1] for r in cur.fetchall()}

        # 4. Fetch assembly guides (torque and wrench specifications)
        current_nominals = {r["nominal"].upper().replace(" ", "") for r in param_rows}
        cur.execute("""
            SELECT nominal, stress_area, hex_key, hex_wrench_af, socket_size,
                   preload_8_8, dry_torque_8_8, lube_torque_8_8,
                   preload_10_9, dry_torque_10_9, lube_torque_10_9,
                   preload_12_9, dry_torque_12_9, lube_torque_12_9
            FROM fastener_assembly_guides
            ORDER BY id ASC
        """)
        guide_rows = cur.fetchall()
        assembly_guides = []
        for gr in guide_rows:
            g_dict = dict(gr)
            g_dict["is_current"] = (g_dict["nominal"].upper() in current_nominals)
            assembly_guides.append(g_dict)

        return {
            "standard": standard,
            "param_titles": param_titles,
            "param_rows": param_rows,
            "length_titles": length_titles,
            "length_rows": length_rows,
            "tap_holes": tap_holes,
            "assembly_guides": assembly_guides
        }
    finally:
        conn.close()


def get_fastener_hole_charts(chart_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns drill hole reference chart rows."""
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        if chart_type:
            cur.execute(
                "SELECT chart_type, nominal_dia, hole_diameter FROM fastener_hole_charts WHERE chart_type = ? ORDER BY hole_diameter ASC",
                (chart_type,)
            )
        else:
            cur.execute(
                "SELECT chart_type, nominal_dia, hole_diameter FROM fastener_hole_charts ORDER BY chart_type ASC, hole_diameter ASC"
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_fastener_assembly_guides(nominal: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns torque specs and tool sizing assembly guidelines."""
    conn = get_connection(FASTENERS_DB_PATH)
    if not conn:
        return []
    try:
        cur = conn.cursor()
        if nominal:
            cur.execute("SELECT * FROM fastener_assembly_guides WHERE nominal = ? OR lower(nominal) = lower(?)", (nominal, nominal))
        else:
            cur.execute("SELECT * FROM fastener_assembly_guides ORDER BY id ASC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


