from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List

from db.database import get_db
from app.services import external_library_service as lib_svc
from app.services.inventory_service import InventoryService
from app.schemas.inventory import PartToInventoryAdd

router = APIRouter()


@router.get("/status")
def get_libraries_status():
    """Get current status, availability, and record counts for all 3 external libraries."""
    return lib_svc.get_libraries_status()


@router.get("/search")
def search_libraries(
    q: str = Query(..., min_length=1, description="Search query keyword or part number"),
    target: str = Query("all", description="Target library: 'all', 'altium', 'kicad', or 'jlcparts'"),
    limit: int = Query(20, ge=1, le=100)
):
    """
    Search across external component libraries (Altium, KiCad, JLCParts).
    """
    target = target.lower()
    if target == "altium":
        return {"altium": lib_svc.search_altium(q, page_size=limit)}
    elif target == "kicad":
        return {"kicad": lib_svc.search_kicad(q, page_size=limit)}
    elif target == "jlcparts":
        return {"jlcparts": lib_svc.search_jlcparts(q, page_size=limit)}
    else:
        return lib_svc.search_all_libraries(q, limit_each=limit)


# ==========================================
# Altium Endpoints
# ==========================================

@router.get("/altium/categories")
def get_altium_categories():
    """Get distinct component categories available in Altium libraries."""
    return lib_svc.get_altium_categories()


@router.get("/altium/packages")
def get_altium_packages():
    """Get distinct packages available in Altium libraries."""
    return lib_svc.get_altium_packages()


@router.get("/altium")
def search_altium_library(
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
        page_size=page_size
    )


@router.get("/altium/{comp_id}")
def get_altium_component_detail(comp_id: int):
    """Get full details of a specific Altium component including all parameters."""
    item = lib_svc.get_altium_component(comp_id)
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
def get_jlcparts_categories():
    """Get hierarchical categories and subcategories from JLCParts database."""
    return lib_svc.get_jlcparts_categories()


@router.get("/jlcparts")
def search_jlcparts_library(
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
        page_size=page_size
    )


@router.get("/jlcparts/{lcsc}")
def get_jlcparts_component_detail(lcsc: int):
    """Get full details of a specific JLCParts component including all attributes and pricing."""
    item = lib_svc.get_jlcparts_component(lcsc)
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
