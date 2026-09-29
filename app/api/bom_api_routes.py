"""
BOM (Bill of Materials) API Router for PartShelf.
Handles BOM file upload, interactive matching preview, and import execution.
"""

import os
import re
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from db.database import get_db
from app.i18n import get_current_language
from app.services.bom_service import parse_bom_file, analyze_bom_matching, execute_bom_import
from app.models.custom_component import CustomComponent

router = APIRouter()


class BomImportItem(BaseModel):
    row_index: int
    quantity: int = 1
    designator: Optional[str] = ""
    footprint: Optional[str] = ""
    comment: Optional[str] = ""
    manufacturer_part: Optional[str] = ""
    manufacturer: Optional[str] = ""
    status: str = "unmatched"
    library_source: Optional[str] = None
    external_part_id: Optional[str] = None
    inventory_part_id: Optional[int] = None
    selected: bool = True
    auto_create_zero_stock: bool = True
    is_custom: bool = False
    custom_name: Optional[str] = None
    custom_manufacturer: Optional[str] = None
    custom_package: Optional[str] = None
    custom_description: Optional[str] = None


class BomImportRequest(BaseModel):
    target_type: str = "new"  # 'new' or 'existing'
    project_name: Optional[str] = None
    project_description: Optional[str] = None
    existing_project_id: Optional[int] = None
    quantity_strategy: str = "overwrite"  # 'overwrite' or 'add'
    items: List[BomImportItem]


class CustomPartCreateRequest(BaseModel):
    name: str
    manufacturer: Optional[str] = "Generic"
    package: Optional[str] = "Standard"
    part_type: Optional[str] = "Custom"
    description: Optional[str] = None


@router.post("/preview")
async def preview_bom(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Parses an uploaded BOM file (.xlsx, .xls, .csv) and performs library matching.
    Returns preview summary and matching items for user review.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file has no filename"
        )

    fn = file.filename
    ext = os.path.splitext(fn)[1].lower()
    if ext not in [".xlsx", ".xls", ".csv"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Only .xlsx, .xls, and .csv are supported."
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty."
        )

    try:
        parsed_rows = parse_bom_file(content, fn)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse BOM file: {str(e)}"
        )

    if not parsed_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid component rows could be extracted from the BOM file."
        )

    lang = get_current_language(request)
    analysis = analyze_bom_matching(parsed_rows, db, lang=lang)

    # Clean filename for suggested project name
    base_name = os.path.splitext(fn)[0]
    # Remove leading 'BOM_' or 'BOM__'
    suggested_name = re.sub(r'^[bB][oO][mM]_+', '', base_name).strip()
    if not suggested_name:
        suggested_name = base_name

    return {
        "filename": fn,
        "suggested_project_name": suggested_name,
        "total_rows": analysis["total_rows"],
        "in_inventory_count": analysis["in_inventory_count"],
        "matched_library_count": analysis["matched_library_count"],
        "unmatched_count": analysis["unmatched_count"],
        "items": analysis["items"],
    }


@router.post("/import")
def import_bom(
    payload: BomImportRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Executes the BOM import with user confirmed matching items.
    """
    if payload.target_type == "new" and not (payload.project_name or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_name is required when creating a new project"
        )

    if payload.target_type == "existing" and not payload.existing_project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="existing_project_id is required when importing into an existing project"
        )

    try:
        raw_items = [it.model_dump() for it in payload.items]
        result = execute_bom_import(
            db=db,
            target_type=payload.target_type,
            project_name=payload.project_name,
            project_description=payload.project_description,
            existing_project_id=payload.existing_project_id,
            quantity_strategy=payload.quantity_strategy,
            items=raw_items
        )
        return result
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while importing BOM: {str(e)}"
        )


@router.post("/custom_part")
def create_custom_component(
    payload: CustomPartCreateRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Creates a new custom component in custom_components table.
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Component name cannot be empty"
        )

    custom = CustomComponent(
        name=name,
        manufacturer=payload.manufacturer.strip() if payload.manufacturer else "Generic",
        package=payload.package.strip() if payload.package else "Standard",
        part_type=payload.part_type.strip() if payload.part_type else "Custom",
        description=payload.description.strip() if payload.description else None
    )
    db.add(custom)
    db.commit()
    db.refresh(custom)

    return {
        "id": custom.id,
        "name": custom.name,
        "manufacturer": custom.manufacturer,
        "package": custom.package,
        "part_type": custom.part_type,
        "description": custom.description
    }
