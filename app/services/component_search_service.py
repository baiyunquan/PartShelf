"""Shared JLCParts candidate lookup and exact LCSC-code resolution."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from app.services import lcsc_dynamic_service


LOGGER = logging.getLogger(__name__)
MAX_BOM_LOOKUP_WORKERS = 4
_LCSC_CODE = re.compile(r"^[Cc]?(\d{3,10})$")


def normalize_lcsc_code(value: Any) -> Optional[int]:
    """Normalize a bare or C-prefixed LCSC part number."""
    match = _LCSC_CODE.fullmatch(str(value or "").strip())
    return int(match.group(1)) if match else None


def get_local_lcsc_component(code: Any) -> Optional[Dict[str, Any]]:
    """Read one JLCParts catalog row and its image metadata."""
    lcsc = normalize_lcsc_code(code)
    if lcsc is None:
        return None

    conn = None
    try:
        conn = sqlite3.connect(lcsc_dynamic_service.JLCPARTS_DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        row = conn.execute(
            """
            SELECT j.*, l.image, l.url_slug
            FROM jlc_components j
            LEFT JOIN lcsc_components l ON l.lcsc = j.lcsc
            WHERE j.lcsc = ?
            """,
            (lcsc,),
        ).fetchone()
        return dict(row) if row else None
    except (OSError, sqlite3.Error) as exc:
        LOGGER.warning("Could not read JLCParts component C%s: %s", lcsc, exc)
        return None
    finally:
        if conn:
            conn.close()


def resolve_exact_lcsc_component(
    code: Any, *, refresh: bool = False
) -> Optional[Dict[str, Any]]:
    """Return a local exact-code component, fetching and caching when needed."""
    lcsc = normalize_lcsc_code(code)
    if lcsc is None:
        return None

    local = get_local_lcsc_component(lcsc)
    stale_dynamic = bool(
        local
        and local.get("library_type") == "lcsc_dynamic"
        and lcsc_dynamic_service.is_component_stale(local.get("fetched_at"))
    )
    if not refresh and local is not None and not stale_dynamic:
        if local.get("library_type") == "lcsc_dynamic":
            local["source"] = "lcsc_dynamic"
        return local

    try:
        fetched = lcsc_dynamic_service.get_or_fetch_component(lcsc)
    except Exception as exc:
        LOGGER.warning("LCSC lookup failed for C%s: %s", lcsc, exc)
        fetched = None
    if fetched:
        fetched["source"] = "lcsc_dynamic"
        return fetched

    if local and local.get("library_type") == "lcsc_dynamic":
        local["source"] = "lcsc_dynamic"
    return local


def resolve_search_lcsc_query(query: str) -> Optional[Dict[str, Any]]:
    """Dynamically resolve exact C-number searches only when local data is absent or stale."""
    lcsc = lcsc_dynamic_service.is_exact_lcsc_code(query or "")
    if lcsc is None:
        return None

    local = get_local_lcsc_component(lcsc)
    if local is not None and not (
        local.get("library_type") == "lcsc_dynamic"
        and lcsc_dynamic_service.is_component_stale(local.get("fetched_at"))
    ):
        return None
    return resolve_exact_lcsc_component(lcsc, refresh=True)


def resolve_bom_lcsc_codes(codes: Iterable[Any]) -> Dict[int, Dict[str, Any]]:
    """Refresh distinct unmatched BOM C-numbers with bounded concurrency."""
    normalized = sorted({code for value in codes if (code := normalize_lcsc_code(value)) is not None})
    if not normalized:
        return {}

    results: Dict[int, Dict[str, Any]] = {}

    def resolve(code: int) -> tuple[int, Optional[Dict[str, Any]]]:
        try:
            return code, resolve_exact_lcsc_component(code, refresh=True)
        except Exception as exc:
            LOGGER.warning("Could not resolve BOM LCSC code C%s: %s", code, exc)
            return code, get_local_lcsc_component(code)

    with ThreadPoolExecutor(max_workers=min(MAX_BOM_LOOKUP_WORKERS, len(normalized))) as pool:
        futures = [pool.submit(resolve, code) for code in normalized]
        for future in as_completed(futures):
            code, item = future.result()
            if item:
                results[code] = item
    return results


def find_jlc_model(model: str, connection) -> List[Dict[str, Any]]:
    """Read local JLCParts exact-model candidates through the shared query layer."""
    model = (model or "").strip()
    if not connection or len(model) < 4:
        return []
    return [dict(row) for row in connection.execute(
        "SELECT * FROM jlc_components WHERE mfr = ?", (model,)
    )]


def find_jlc_by_category_package(
    category: str, package: str, connection
) -> List[Dict[str, Any]]:
    """Read local JLCParts passive candidates by category and package."""
    if not connection or not category or not package:
        return []
    package_arg = f"%{package}%" if package.startswith("3225") else f"{package}%"
    return [dict(row) for row in connection.execute(
        "SELECT * FROM jlc_components WHERE category LIKE ? AND package LIKE ?",
        (f"{category}%", package_arg),
    )]
