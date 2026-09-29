"""
Unified Global Search API Router for PartShelf.
Coordinates search requests across all 4 component sources:
- Local Inventory (parts.db via InventoryService)
- JLCPCB In-stock Parts (jlcparts.db via external_library_service)
- Altium JLCPCB Libraries (altium_library.db via external_library_service)
- KiCad Symbol Libraries (kicad_symbols.db via external_library_service)

All underlying search functions remain distributed in their respective services.
"""

import math
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List

from db.database import get_db
from app.i18n import get_current_language
from app.services.inventory_service import InventoryService
from app.services import external_library_service as lib_svc

router = APIRouter()


@router.get("/quick")
def quick_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search keyword for instant preview"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Lightweight quick search across all libraries for top navbar live autocomplete dropdown.
    Returns top 3-4 matches from each library plus total match counts.
    """
    query = (q or "").strip()
    if not query:
        return {
            "query": "",
            "total_matches": 0,
            "inventory": {"total": 0, "items": []},
            "jlcparts": {"total": 0, "items": []},
            "altium": {"total": 0, "items": []},
            "kicad": {"total": 0, "items": []},
        }

    lang = get_current_language(request)

    # 1. Local Inventory
    inv_all = InventoryService.search(query, db, lang=lang)
    inv_total = len(inv_all)
    inv_items = [
        {
            "id": p.id,
            "name": p.name,
            "package": p.package,
            "manufacturer": p.manufacturer,
            "quantity": p.quantity,
            "storage_location": p.storage_location,
            "url": f"/component_details?part_id={p.id}"
        }
        for p in inv_all[:3]
    ]

    # 2. JLCParts
    jlc_res = lib_svc.search_jlcparts(query, page=1, page_size=4, lang=lang)
    jlc_total = jlc_res.get("total", 0)
    jlc_items = [
        {
            "lcsc": item["lcsc"],
            "mfr": item.get("mfr") or f"C{item['lcsc']}",
            "package": item.get("package"),
            "image": item.get("image_url_small"),
            "stock": item.get("stock", 0),
            "price": item.get("price_breaks", [{}])[0].get("price") if item.get("price_breaks") else None,
            "url": f"/libraries/jlcparts/{item['lcsc']}"
        }
        for item in jlc_res.get("items", [])[:4]
    ]

    # 3. Altium
    altium_res = lib_svc.search_altium(query, page=1, page_size=4, lang=lang)
    altium_total = altium_res.get("total", 0)
    altium_items = [
        {
            "id": item["id"],
            "lib_reference": item.get("lib_reference") or item.get("mfr_part_number") or f"Altium #{item['id']}",
            "package": item.get("package"),
            "lcsc_part": item.get("lcsc_part"),
            "url": f"/libraries/altium/{item['id']}"
        }
        for item in altium_res.get("items", [])[:4]
    ]

    # 4. KiCad
    kicad_res = lib_svc.search_kicad(query, page=1, page_size=4)
    kicad_total = kicad_res.get("total", 0)
    kicad_items = [
        {
            "id": item["id"],
            "name": item.get("value") or item.get("name") or f"KiCad #{item['id']}",
            "library": item.get("library"),
            "footprint": item.get("footprint"),
            "url": f"/libraries/kicad/{item['id']}"
        }
        for item in kicad_res.get("items", [])[:4]
    ]

    # 5. Fasteners
    fasteners_res = lib_svc.query_fasteners(page=1, page_size=4, query=query, lang=lang)
    fasteners_total = fasteners_res.get("total", 0)
    fasteners_items = [
        {
            "id": item["id"],
            "name": item.get("standard_name_localized") or item.get("standard_name") or item.get("standard_code"),
            "category": item.get("category_group_zh") or item.get("category_group"),
            "authority": item.get("authority"),
            "url": f"/libraries/fasteners/{item['standard_code']}"
        }
        for item in fasteners_res.get("items", [])[:4]
    ]

    total_matches = inv_total + jlc_total + altium_total + kicad_total + fasteners_total

    return {
        "query": query,
        "total_matches": total_matches,
        "inventory": {"total": inv_total, "items": inv_items},
        "jlcparts": {"total": jlc_total, "items": jlc_items},
        "altium": {"total": altium_total, "items": altium_items},
        "kicad": {"total": kicad_total, "items": kicad_items},
        "fasteners": {"total": fasteners_total, "items": fasteners_items},
    }


@router.get("/aggregate")
def aggregate_search(
    request: Request,
    q: Optional[str] = Query("", description="Keyword, model or LCSC part number"),
    tab: str = Query("all", description="Target tab: 'all', 'inventory', 'jlcparts', 'altium', 'kicad', 'fasteners'"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Main aggregated search endpoint serving the Global Search Center (/search).
    Dispatches to the requested library tab or returns an aggregated multi-library overview.
    """
    query = (q or "").strip()
    tab = (tab or "all").lower()
    lang = get_current_language(request)

    # Tab 1: All (Overview of all libraries)
    if tab == "all":
        # Inventory preview
        inv_all = InventoryService.search(query, db, lang=lang) if query else []
        inv_total = len(inv_all)
        inv_preview = [
            {
                "id": p.id,
                "name": p.name,
                "package": p.package,
                "manufacturer": p.manufacturer,
                "part_type": p.part_type,
                "quantity": p.quantity,
                "storage_location": p.storage_location,
                "library_source": p.library_source,
                "external_part_id": p.external_part_id,
                "url": f"/component_details?part_id={p.id}"
            }
            for p in inv_all[:5]
        ]

        # JLCParts preview
        jlc_res = lib_svc.search_jlcparts(query, page=1, page_size=5, lang=lang) if query else {"total": 0, "items": []}
        jlc_total = jlc_res.get("total", 0)

        # Altium preview
        altium_res = lib_svc.search_altium(query, page=1, page_size=5, lang=lang) if query else {"total": 0, "items": []}
        altium_total = altium_res.get("total", 0)

        # KiCad preview
        kicad_res = lib_svc.search_kicad(query, page=1, page_size=5) if query else {"total": 0, "items": []}
        kicad_total = kicad_res.get("total", 0)

        # Fasteners preview
        fasteners_res = lib_svc.query_fasteners(page=1, page_size=5, query=query, lang=lang) if query else {"total": 0, "items": []}
        fasteners_total = fasteners_res.get("total", 0)

        total_matches = inv_total + jlc_total + altium_total + kicad_total + fasteners_total

        return {
            "query": query,
            "tab": "all",
            "total_matches": total_matches,
            "counts": {
                "inventory": inv_total,
                "jlcparts": jlc_total,
                "altium": altium_total,
                "kicad": kicad_total,
                "fasteners": fasteners_total,
            },
            "inventory": {"total": inv_total, "items": inv_preview},
            "jlcparts": {"total": jlc_total, "items": jlc_res.get("items", [])},
            "altium": {"total": altium_total, "items": altium_res.get("items", [])},
            "kicad": {"total": kicad_total, "items": kicad_res.get("items", [])},
            "fasteners": {"total": fasteners_total, "items": fasteners_res.get("items", [])},
        }

    # Tab 2: Inventory
    elif tab == "inventory":
        inv_all = InventoryService.search(query, db, lang=lang)
        total = len(inv_all)
        total_pages = math.ceil(total / page_size) if total > 0 else 1
        page = min(page, total_pages) if total_pages > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        items = [
            {
                "id": p.id,
                "name": p.name,
                "package": p.package,
                "manufacturer": p.manufacturer,
                "part_type": p.part_type,
                "quantity": p.quantity,
                "storage_location": p.storage_location,
                "library_source": p.library_source,
                "external_part_id": p.external_part_id,
                "image_url": p.image_url,
                "note": p.note,
                "projects": [pj.dict() for pj in p.projects] if p.projects else [],
                "url": f"/component_details?part_id={p.id}"
            }
            for p in inv_all[start_idx:end_idx]
        ]
        return {
            "query": query,
            "tab": "inventory",
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    # Tab 3: JLCParts
    elif tab == "jlcparts":
        res = lib_svc.search_jlcparts(
            query=query,
            page=page,
            page_size=page_size,
            lang=lang
        )
        res["query"] = query
        res["tab"] = "jlcparts"
        return res

    # Tab 4: Altium
    elif tab == "altium":
        res = lib_svc.search_altium(
            query=query,
            page=page,
            page_size=page_size,
            lang=lang
        )
        res["query"] = query
        res["tab"] = "altium"
        return res

    # Tab 5: KiCad
    elif tab == "kicad":
        res = lib_svc.search_kicad(
            query=query,
            page=page,
            page_size=page_size
        )
        res["query"] = query
        res["tab"] = "kicad"
        return res

    # Tab 6: Fasteners
    elif tab == "fasteners":
        res = lib_svc.query_fasteners(
            query=query,
            page=page,
            page_size=page_size,
            lang=lang,
        )
        res["query"] = query
        res["tab"] = "fasteners"
        return res

    else:
        return {"query": query, "tab": tab, "items": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 1}

