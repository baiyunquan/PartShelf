"""Common constants, connection management, startup checks, and custom row key helpers."""

import os
import sys
import sqlite3
import json
import re
import hashlib
import logging
from urllib.parse import quote, unquote
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.services.numeric_alias_index import prepare_numeric_aliases

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "libraries"
SCRIPTS_DIR = BASE_DIR / "scripts"

JLCPARTS_DB_PATH = DATA_DIR / "jlcparts.db"
ALTIUM_DB_PATH = DATA_DIR / "altium_library.db"
KICAD_DB_PATH = DATA_DIR / "kicad_symbols.db"
FASTENERS_DB_PATH = DATA_DIR / "fasteners.db"
STATIC_PARTS_DIR = BASE_DIR / "static" / "images" / "parts"

def get_db_path(name: str, default_path: Path) -> Path:
    """Dynamically resolve database path, allowing test monkeypatching on external_library_service."""
    facade = sys.modules.get("app.services.external_library_service")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return default_path

def _custom_row_key(nominal: str, payload: Dict[str, Any]) -> str:
    encoded_nominal = quote(nominal.strip(), safe="")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"user:{encoded_nominal}:{digest}"


def _custom_nominal_from_row_key(row_key: str) -> str:
    if not str(row_key).startswith("user:"):
        return str(row_key)
    parts = str(row_key).split(":", 2)
    encoded = unquote(parts[1]) if len(parts) == 3 else str(row_key)
    return encoded.rsplit("@", 1)[0] if "@" in encoded else encoded


def _normalize_custom_nominal(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    metric = re.fullmatch(r"M\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if metric:
        try:
            size = format(Decimal(metric.group(1)).normalize(), "f")
            return f"M{size}"
        except InvalidOperation:
            return text
    mixed_inch = re.fullmatch(r"(\d+)\s+(\d+\s*/\s*\d+)(?:\s*(?:in|inch|\"))?", text, re.IGNORECASE)
    if mixed_inch:
        fraction = re.sub(r"\s+", "", mixed_inch.group(2))
        return f"{mixed_inch.group(1)} {fraction}in"
    fraction_inch = re.fullmatch(r"(\d+\s*/\s*\d+)(?:\s*(?:in|inch|\"))?", text, re.IGNORECASE)
    if fraction_inch:
        normalized_fraction = re.sub(r"\s+", "", fraction_inch.group(1))
        return f"{normalized_fraction}in"
    inch = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*(?:in|inch|\"))", text, re.IGNORECASE)
    if inch:
        return f"{inch.group(1)}in"
    return text


def _custom_length_from_row_key(row_key: str) -> Optional[str]:
    if not str(row_key).startswith("user:"):
        return None
    parts = str(row_key).split(":", 2)
    encoded = unquote(parts[1]) if len(parts) == 3 else ""
    return encoded.rsplit("@", 1)[1] if "@" in encoded else None


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

    for source, path in (("jlcparts", JLCPARTS_DB_PATH), ("altium", ALTIUM_DB_PATH),
                         ("kicad", KICAD_DB_PATH)):
        conn = get_connection(path)
        if conn:
            try:
                status[source]["numeric_aliases_ready"] = prepare_numeric_aliases(conn, source)
            finally:
                conn.close()
    return status


def get_connection(db_path: Path) -> Optional[sqlite3.Connection]:
    """Open an installed component library with read/write access."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def get_libraries_status() -> Dict[str, Any]:
    """Return availability and statistics for all installed reference libraries."""
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


