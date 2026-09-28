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
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

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


def search_altium(query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection(ALTIUM_DB_PATH)
    if not conn:
        return []

    cur = conn.cursor()
    sql = """
    SELECT id, lib_reference, lcsc_part, category, package, manufacturer,
           mfr_part_number, basic_part, description, resistance, capacitance,
           inductance, tolerance, voltage_rating, power_rating, datasheet_url,
           jlcpcb_url, lcsc_url, parameters_json, source_file
    FROM altium_components
    WHERE (lib_reference LIKE ? OR lcsc_part LIKE ? OR mfr_part_number LIKE ? OR description LIKE ?)
    """
    params = [f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"]

    if category:
        sql += " AND category = ?"
        params.append(category)

    sql += " LIMIT ?"
    params.append(limit)

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        if r.get("parameters_json"):
            try:
                r["parameters"] = json.loads(r["parameters_json"])
            except Exception:
                r["parameters"] = {}
    return rows


def search_kicad(query: str, library: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection(KICAD_DB_PATH)
    if not conn:
        return []

    cur = conn.cursor()
    sql = """
    SELECT id, library, name, extends, reference, value, footprint,
           datasheet, description, keywords, fp_filters, in_bom, on_board,
           properties_json, source_file
    FROM kicad_symbols
    WHERE (name LIKE ? OR value LIKE ? OR keywords LIKE ? OR description LIKE ?)
    """
    params = [f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"]

    if library:
        sql += " AND library = ?"
        params.append(library)

    sql += " LIMIT ?"
    params.append(limit)

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        if r.get("properties_json"):
            try:
                r["properties"] = json.loads(r["properties_json"])
            except Exception:
                r["properties"] = {}
    return rows


def search_jlcparts(query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection(JLCPARTS_DB_PATH)
    if not conn:
        return []

    cur = conn.cursor()
    sql = """
    SELECT j.lcsc, j.category, j.subcategory, j.mfr, j.package, j.joints,
           j.manufacturer, j.library_type, j.preferred, j.stock, j.price,
           j.description, j.datasheet, j.attributes, l.image, l.url_slug
    FROM jlc_components j
    LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
    WHERE (j.mfr LIKE ? OR ('C' || j.lcsc) LIKE ? OR j.description LIKE ?)
    """
    params = [f"%{query}%", f"%{query}%", f"%{query}%"]

    if category:
        sql += " AND j.category = ?"
        params.append(category)

    sql += " LIMIT ?"
    params.append(limit)

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
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

    return rows


def search_all_libraries(query: str, limit_each: int = 20) -> Dict[str, Any]:
    """Unified cross-library search across Altium, KiCad, and JLCParts."""
    return {
        "query": query,
        "altium": search_altium(query, limit=limit_each),
        "kicad": search_kicad(query, limit=limit_each),
        "jlcparts": search_jlcparts(query, limit=limit_each),
    }
