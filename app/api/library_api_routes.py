from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any

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
        return {"altium": lib_svc.search_altium(q, limit=limit)}
    elif target == "kicad":
        return {"kicad": lib_svc.search_kicad(q, limit=limit)}
    elif target == "jlcparts":
        return {"jlcparts": lib_svc.search_jlcparts(q, limit=limit)}
    else:
        return lib_svc.search_all_libraries(q, limit_each=limit)


@router.get("/altium")
def search_altium_library(
    q: str = Query(..., min_length=1),
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    """Search specifically within Altium JLCPCB component libraries."""
    return lib_svc.search_altium(q, category=category, limit=limit)


@router.get("/kicad")
def search_kicad_library(
    q: str = Query(..., min_length=1),
    library: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    """Search specifically within KiCad symbol libraries."""
    return lib_svc.search_kicad(q, library=library, limit=limit)


@router.get("/jlcparts")
def search_jlcparts_library(
    q: str = Query(..., min_length=1),
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    """Search specifically within JLCParts database (includes image URLs and pricing)."""
    return lib_svc.search_jlcparts(q, category=category, limit=limit)


@router.post("/import_to_inventory")
def import_external_to_inventory(
    source: str = Query(..., description="'altium', 'kicad', or 'jlcparts'"),
    part_id: str = Query(..., description="Component identifier or LCSC part number"),
    quantity: int = Query(1, ge=0),
    db: Session = Depends(get_db)
):
    """
    Optionally import an external component into PartShelf's local inventory database (partshelf.db).
    """
    part_name = ""
    package_name = ""
    type_name = ""
    mfr_name = ""

    if source == "jlcparts":
        results = lib_svc.search_jlcparts(part_id, limit=1)
        if not results:
            raise HTTPException(status_code=404, detail="Component not found in JLCParts")
        item = results[0]
        part_name = item.get("mfr") or f"C{item.get('lcsc')}"
        package_name = item.get("package") or "Standard"
        type_name = item.get("category") or "General"
        mfr_name = item.get("manufacturer") or "Unknown"

    elif source == "altium":
        results = lib_svc.search_altium(part_id, limit=1)
        if not results:
            raise HTTPException(status_code=404, detail="Component not found in Altium library")
        item = results[0]
        part_name = item.get("mfr_part_number") or item.get("lib_reference")
        package_name = item.get("package") or "Standard"
        type_name = item.get("category") or "General"
        mfr_name = item.get("manufacturer") or "Unknown"

    elif source == "kicad":
        results = lib_svc.search_kicad(part_id, limit=1)
        if not results:
            raise HTTPException(status_code=404, detail="Symbol not found in KiCad symbols")
        item = results[0]
        part_name = item.get("name") or item.get("value")
        package_name = item.get("footprint") or "Standard"
        type_name = item.get("library") or "General"
        mfr_name = "KiCad Standard"

    else:
        raise HTTPException(status_code=400, detail="Invalid source library")

    inv_svc = InventoryService(db)
    inv_item = inv_svc.create_part(
        PartToInventoryAdd(
            name=part_name,
            package=package_name,
            part_type=type_name,
            manufacturer=mfr_name,
            quantity=quantity
        )
    )
    return {"message": "Imported to local inventory successfully", "part_id": inv_item.id}
