"""On-demand lookup and persistent cache for exact LCSC component numbers."""

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent.parent.parent
JLCPARTS_DB_PATH = BASE_DIR / "data" / "libraries" / "jlcparts.db"
CACHE_TTL_SECONDS = 6 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 8
LOGGER = logging.getLogger(__name__)


def fetch_lcsc_product(lcsc: int) -> Optional[Dict[str, Any]]:
    """Fetch one exact product from LCSC's public product detail endpoint."""
    code = f"C{int(lcsc)}"
    url = "https://wmsc.lcsc.com/ftps/wm/product/detail?" + urlencode(
        {"productCode": code}
    )
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        LOGGER.info("LCSC lookup unavailable for %s: %s", code, exc)
        return None

    if not isinstance(body, dict) or body.get("code") != 200:
        return None
    product = body.get("result")
    if not isinstance(product, dict):
        return None

    returned_code = str(product.get("productCode") or "").strip().upper()
    if returned_code != code:
        return None
    return product


def _open_library_db() -> sqlite3.Connection:
    if not JLCPARTS_DB_PATH.exists():
        raise FileNotFoundError(f"JLCParts database does not exist: {JLCPARTS_DB_PATH}")
    conn = sqlite3.connect(JLCPARTS_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _read_cached_component(lcsc: int) -> Optional[Dict[str, Any]]:
    conn = _open_library_db()
    try:
        row = conn.execute(
            """
            SELECT j.*, l.image, l.url_slug
            FROM jlc_components j
            LEFT JOIN lcsc_components l ON l.lcsc = j.lcsc
            WHERE j.lcsc = ? AND j.library_type = 'lcsc_dynamic'
            """,
            (lcsc,),
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def _write_cached_component(item: Dict[str, Any]) -> bool:
    conn = _open_library_db()
    now = int(time.time())
    stock = int(item.get("stock", -1))
    last_on_stock = now if stock > 0 else 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = conn.execute(
            """
            INSERT INTO jlc_components (
                lcsc, fetched_at, present, sync_seen, category, subcategory,
                mfr, package, joints, manufacturer, library_type, preferred,
                last_on_stock, description, datasheet, stock, price, attributes,
                rohs, eccn, assembly, assembly_process, assembly_mode,
                website_component_id, attrition
            ) VALUES (?, ?, 1, 0, ?, ?, ?, ?, ?, ?, 'lcsc_dynamic', 0, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, '{}')
            ON CONFLICT(lcsc) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                present = excluded.present,
                sync_seen = excluded.sync_seen,
                category = excluded.category,
                subcategory = excluded.subcategory,
                mfr = excluded.mfr,
                package = excluded.package,
                joints = excluded.joints,
                manufacturer = excluded.manufacturer,
                library_type = excluded.library_type,
                preferred = excluded.preferred,
                last_on_stock = excluded.last_on_stock,
                description = excluded.description,
                datasheet = excluded.datasheet,
                stock = excluded.stock,
                price = excluded.price,
                attributes = excluded.attributes,
                rohs = excluded.rohs,
                eccn = excluded.eccn,
                assembly = excluded.assembly,
                assembly_process = excluded.assembly_process,
                assembly_mode = excluded.assembly_mode,
                website_component_id = excluded.website_component_id,
                attrition = excluded.attrition
            """,
            (
                item["lcsc"], now, item.get("category") or "",
                item.get("subcategory") or "", item.get("mfr") or "",
                item.get("package") or "", item.get("joints") or 0,
                item.get("manufacturer") or "", last_on_stock,
                item.get("description") or "", item.get("datasheet") or "",
                stock, item.get("price") or "", item.get("attributes") or "{}",
                item.get("rohs"), item.get("eccn") or "-",
            ),
        )
        if result.rowcount == 0:
            conn.rollback()
            return False

        conn.execute(
            """
            INSERT INTO lcsc_components (
                lcsc, fetched_at, manufacturer, attributes, image, url_slug
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(lcsc) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                manufacturer = excluded.manufacturer,
                attributes = excluded.attributes,
                image = excluded.image,
                url_slug = excluded.url_slug
            """,
            (
                item["lcsc"], now, item.get("manufacturer") or "",
                item.get("attributes") or "{}", item.get("image"), item.get("url_slug"),
            ),
        )
        conn.commit()
        item["fetched_at"] = now
        item["present"] = 1
        item["sync_seen"] = 0
        item["last_on_stock"] = last_on_stock
        item["eccn"] = item.get("eccn") or "-"
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _price_string(product: Dict[str, Any]) -> str:
    tiers = []
    for entry in product.get("productPriceList") or []:
        if not isinstance(entry, dict):
            continue
        try:
            quantity = int(entry.get("ladder"))
        except (TypeError, ValueError):
            continue
        price = entry.get("usdPrice")
        if price is None:
            price = entry.get("productPrice")
        if quantity > 0 and price is not None:
            tiers.append((quantity, str(price)))

    tiers.sort(key=lambda tier: tier[0])
    ranges = []
    for index, (quantity, price) in enumerate(tiers):
        if index + 1 < len(tiers):
            upper = tiers[index + 1][0] - 1
            quantity_range = (
                f"{quantity}-{upper}" if upper >= quantity else str(quantity)
            )
        else:
            quantity_range = f"{quantity}-"
        ranges.append(f"{quantity_range}:{price}")
    return ",".join(ranges)


def normalize_lcsc_product(lcsc: int, product: Dict[str, Any]) -> Dict[str, Any]:
    """Map public LCSC fields to the shape consumed by JLCParts pages."""
    attributes: Dict[str, Any] = {}
    for parameter in product.get("paramVOList") or []:
        if not isinstance(parameter, dict):
            continue
        name = parameter.get("paramNameEn") or parameter.get("paramName")
        value = parameter.get("paramValueEn") or parameter.get("paramValue")
        if name and value not in (None, "", "-"):
            attributes[str(name)] = value

    image_url = next(
        (
            image
            for image in (product.get("productImages") or [])
            if isinstance(image, str)
        ),
        None,
    )
    image = Path(urlparse(image_url).path).name if image_url else None
    stock = product.get("stockNumber")
    try:
        stock = int(stock)
    except (TypeError, ValueError):
        stock = -1

    category = product.get("parentCatalogName") or ""
    if not category:
        parents = product.get("parentCatalogList") or []
        if parents and isinstance(parents[0], dict):
            category = (
                parents[0].get("catalogNameEn")
                or parents[0].get("catalogName")
                or ""
            )

    return {
        "lcsc": lcsc,
        "category": category,
        "subcategory": product.get("catalogName") or product.get("wmCatalogNameEn") or "",
        "mfr": product.get("productModel") or product.get("title") or f"C{lcsc}",
        "package": product.get("encapStandard") or "",
        "joints": 0,
        "manufacturer": product.get("brandNameEn") or "",
        "library_type": "lcsc_dynamic",
        "preferred": 0,
        "stock": stock,
        "price": _price_string(product),
        "description": (
            product.get("productDescEn")
            or product.get("productIntroEn")
            or product.get("productNameEn")
            or product.get("title")
            or ""
        ),
        "datasheet": product.get("pdfUrl") or product.get("pdfLinkUrl") or "",
        "attributes": json.dumps(attributes, ensure_ascii=False),
        "rohs": 1 if product.get("isRohsCert") else 0,
        "eccn": product.get("eccn") or "-",
        "image": image,
        "url_slug": None,
        "source": "lcsc_dynamic",
        "lcsc_url": f"https://www.lcsc.com/search?q=C{lcsc}",
    }


def get_or_fetch_component(lcsc: int) -> Optional[Dict[str, Any]]:
    """Return a JLCParts database cache row, refreshing it periodically from LCSC."""
    lcsc = int(lcsc)
    try:
        cached = _read_cached_component(lcsc)
    except (OSError, sqlite3.Error) as exc:
        LOGGER.warning("Could not read LCSC cache for C%s: %s", lcsc, exc)
        cached = None
    now = int(time.time())
    if cached and not is_component_stale(cached.get("fetched_at")):
        cached["source"] = "lcsc_dynamic"
        cached["lcsc_url"] = f"https://www.lcsc.com/search?q=C{lcsc}"
        return cached

    try:
        product = fetch_lcsc_product(lcsc)
    except Exception as exc:
        LOGGER.info("LCSC lookup failed for C%s: %s", lcsc, exc)
        product = None

    if product:
        item = normalize_lcsc_product(lcsc, product)
        try:
            if _write_cached_component(item):
                return item
            # A database trigger may have prevented the cache write.
            return None
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            LOGGER.warning("Could not cache LCSC component C%s: %s", lcsc, exc)
            return item

    if cached:
        cached["source"] = "lcsc_dynamic"
        cached["lcsc_url"] = f"https://www.lcsc.com/search?q=C{lcsc}"
        return cached
    return None


def is_component_stale(fetched_at: Any) -> bool:
    try:
        return int(time.time()) - int(fetched_at) >= CACHE_TTL_SECONDS
    except (TypeError, ValueError):
        return True


def is_exact_lcsc_code(query: str) -> Optional[int]:
    match = re.fullmatch(r"C(\d+)", (query or "").strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None
