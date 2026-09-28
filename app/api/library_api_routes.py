import base64
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field, field_validator

from db.database import get_db
from app.services import external_library_service as lib_svc
from app.services.inventory_service import InventoryService
from app.schemas.inventory import PartToInventoryAdd
from app.i18n.category_i18n import category_i18n
from app.i18n import get_current_language

router = APIRouter()


class CrawlerImageUpload(BaseModel):
    lcsc: Union[int, str] = Field(..., description="LCSC part number (integer or integer part of Cxxxx)")
    image_base64: Optional[str] = Field(None, description="Base64-encoded image data, or empty string if no image")
    image_url: Optional[str] = Field(None, description="Original source image URL")
    product_model: Optional[str] = Field(None, description="Component model name or part number")
    has_image: Optional[bool] = Field(True, description="Whether an image was found for this component")

    @field_validator("lcsc", mode="before")
    def parse_lcsc(cls, v):
        if isinstance(v, str):
            v_clean = v.strip().upper().replace("C", "")
            return int(v_clean)
        return int(v)



@router.get("/status")
def get_libraries_status():
    """Get current status, availability, and record counts for all 3 external libraries."""
    return lib_svc.get_libraries_status()


@router.get("/category-translations")
def get_category_translations(request: Request):
    """Get category translations grouped by source and hierarchy level."""
    return category_i18n.get_all(get_current_language(request))


@router.get("/search")
def search_libraries(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query keyword or part number"),
    target: str = Query("all", description="Target library: 'all', 'altium', 'kicad', or 'jlcparts'"),
    limit: int = Query(20, ge=1, le=100)
):
    """
    Search across external component libraries (Altium, KiCad, JLCParts).
    """
    target = target.lower()
    if target == "altium":
        return {"altium": lib_svc.search_altium(q, page_size=limit, lang=get_current_language(request))}
    elif target == "kicad":
        return {"kicad": lib_svc.search_kicad(q, page_size=limit)}
    elif target == "jlcparts":
        return {"jlcparts": lib_svc.search_jlcparts(q, page_size=limit, lang=get_current_language(request))}
    else:
        return lib_svc.search_all_libraries(q, limit_each=limit, lang=get_current_language(request))


# ==========================================
# Altium Endpoints
# ==========================================

@router.get("/altium/categories")
def get_altium_categories(request: Request):
    """Get distinct component categories available in Altium libraries."""
    return lib_svc.get_altium_categories(get_current_language(request))


@router.get("/altium/packages")
def get_altium_packages():
    """Get distinct packages available in Altium libraries."""
    return lib_svc.get_altium_packages()


@router.get("/altium")
def search_altium_library(
    request: Request,
    q: Optional[str] = Query("", description="Keyword, part number or LCSC code"),
    category: Optional[str] = Query(None),
    package: Optional[str] = Query(None),
    basic_only: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200)
):
    """Search or list Altium JLCPCB components with pagination and filtering."""
    return lib_svc.search_altium(
        query=q or "",
        category=category,
        package=package,
        basic_only=basic_only,
        page=page,
        page_size=page_size,
        lang=get_current_language(request)
    )


@router.get("/altium/{comp_id}")
def get_altium_component_detail(comp_id: int, request: Request):
    """Get full details of a specific Altium component including all parameters."""
    item = lib_svc.get_altium_component(comp_id, get_current_language(request))
    if not item:
        raise HTTPException(status_code=404, detail="Altium component not found")
    return item


# ==========================================
# KiCad Endpoints
# ==========================================

@router.get("/kicad/libraries")
def get_kicad_libraries():
    """Get list of distinct library categories available in KiCad symbol libraries."""
    return lib_svc.get_kicad_libraries()


@router.get("/kicad")
def search_kicad_library(
    q: Optional[str] = Query("", description="Keyword, symbol name or description"),
    library: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200)
):
    """Search or list KiCad symbols with pagination and filtering."""
    return lib_svc.search_kicad(
        query=q or "",
        library=library,
        page=page,
        page_size=page_size
    )


@router.get("/kicad/{symbol_id}")
def get_kicad_symbol_detail(symbol_id: int):
    """Get full details of a specific KiCad symbol including raw S-expression."""
    item = lib_svc.get_kicad_symbol(symbol_id)
    if not item:
        raise HTTPException(status_code=404, detail="KiCad symbol not found")
    return item


# ==========================================
# JLCParts Endpoints
# ==========================================

@router.get("/jlcparts/categories")
def get_jlcparts_categories(request: Request):
    """Get hierarchical categories and subcategories from JLCParts database."""
    return lib_svc.get_jlcparts_categories(get_current_language(request))


@router.get("/jlcparts")
def search_jlcparts_library(
    request: Request,
    q: Optional[str] = Query("", description="Keyword, part number or LCSC code"),
    category: Optional[str] = Query(None),
    subcategory: Optional[str] = Query(None),
    package: Optional[str] = Query(None),
    library_type: Optional[str] = Query(None),
    in_stock_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200)
):
    """Search or list JLCParts components with pagination, stock and category filtering."""
    return lib_svc.search_jlcparts(
        query=q or "",
        category=category,
        subcategory=subcategory,
        package=package,
        library_type=library_type,
        in_stock_only=in_stock_only,
        page=page,
        page_size=page_size,
        lang=get_current_language(request)
    )


# ==========================================
# JLCParts Image Harvester Endpoints
# ==========================================

@router.get("/jlcparts/crawler/tasks")
def get_crawler_tasks(
    limit: int = Query(50, ge=1, le=200, description="Batch size of tasks to fetch"),
    cursor: Any = Query(0, description="Cursor offset for pagination (LCSC ID)")
):
    """
    Get a batch of missing-image LCSC part numbers for the ScriptCat crawler.
    """
    try:
        if isinstance(cursor, str) and not cursor.isdigit():
            cursor_val = 0
        else:
            cursor_val = max(0, int(cursor))
    except (ValueError, TypeError):
        cursor_val = 0

    return lib_svc.get_missing_image_lcsc_list(limit=limit, cursor=cursor_val)


@router.get("/jlcparts/crawler/claim-task")
def claim_crawler_task():
    """
    Atomically claims the next pending component for a worker tab.
    Ensures that multiple concurrent browser tabs never process the same item simultaneously.
    """
    task = lib_svc.claim_next_crawler_task()
    if not task:
        return {"status": "empty", "task": None}
    return {"status": "success", "task": task}


@router.post("/jlcparts/crawler/release-task")
def release_crawler_task(lcsc: int = Query(...)):
    """
    Release a claimed task back to the queue if a tab closes or pauses before completing it.
    """
    released = lib_svc.release_crawler_task(lcsc)
    return {"status": "success", "released": released}


@router.post("/jlcparts/crawler/upload")
def upload_crawled_image(payload: CrawlerImageUpload):
    """
    Receive crawled component image data from ScriptCat crawler and persist locally.
    """
    image_bytes = None
    if payload.has_image and payload.image_base64:
        raw_b64 = payload.image_base64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(raw_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {e}")

    result = lib_svc.save_crawled_part_image(
        lcsc=int(payload.lcsc),
        image_bytes=image_bytes,
        image_url=payload.image_url,
        product_model=payload.product_model,
        has_image=bool(image_bytes and len(image_bytes) > 0)
    )
    return result


@router.get("/jlcparts/crawler/stats")
def get_crawler_stats():
    """
    Get summary statistics of image crawling progress.
    """
    return lib_svc.get_crawler_stats()


@router.get("/jlcparts/{lcsc}")
def get_jlcparts_component_detail(lcsc: int, request: Request):
    """Get full details of a specific JLCParts component including all attributes and pricing."""
    item = lib_svc.get_jlcparts_component(lcsc, get_current_language(request))
    if not item:
        raise HTTPException(status_code=404, detail="JLCParts component not found")
    return item


# ==========================================
# Import to Inventory (Backend hook)
# ==========================================

@router.post("/import_to_inventory")
def import_external_to_inventory(
    source: str = Query(..., description="'altium', 'kicad', or 'jlcparts'"),
    part_id: str = Query(..., description="Component identifier or LCSC part number"),
    quantity: int = Query(1, ge=0),
    storage_location: Optional[str] = Query(None),
    note: Optional[str] = Query(None),
    project_ids: Optional[List[int]] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Import an external component into PartShelf's local inventory database (partshelf.db)
    using pure reference architecture.
    """
    part_in = PartToInventoryAdd(
        library_source=source,
        external_part_id=str(part_id),
        quantity=quantity,
        storage_location=storage_location or "Default Storage",
        note=note or "",
        project_ids=project_ids or []
    )
    result = InventoryService.add_part_to_inventory(db, part_in)
    return {"status": "success", "part": result}
