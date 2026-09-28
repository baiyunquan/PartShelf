from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List

from app.schemas.file_template import FileTemplateAdd
from app.schemas.inventory import (
    PartDetailsFlatGet,
    PartInventoryFlatGet,
    PartInventoryQuantity,
    PartInventoryQuantityUpdate,
    PartMetaUpdate,
    PartToInventoryAdd,
)
from app.services.file_service import FileService
from app.services.inventory_service import InventoryService
from db.database import get_db

router = APIRouter()


@router.post("/add_part_to_inventory", response_model=PartInventoryFlatGet)
def add_part_to_inventory(
    part_data: PartToInventoryAdd,
    db: Session = Depends(get_db)
):
    """Add a component to inventory using pure external library reference."""
    return InventoryService.add_part_to_inventory(db, part_data)


@router.post("/update_quantity")
def update_quantity(update: PartInventoryQuantityUpdate, db: Session = Depends(get_db)):
    return InventoryService.update_inventory_quantity(db, update)


@router.post("/update_meta")
def update_part_meta(meta_in: PartMetaUpdate, db: Session = Depends(get_db)):
    """Update storage location and personal notes for an inventory part."""
    return InventoryService.update_part_meta(db, meta_in)


@router.get("/get_parts_inventory")
def get_parts_inventory_list(db: Session = Depends(get_db)):
    return InventoryService.get_parts_inventory_list(db)


@router.get("/get_part_by_id")
def get_part_by_id(part_id: int = Query(..., description="ID of the part to retrieve"), db: Session = Depends(get_db)):
    return InventoryService.get_part_by_id(db, part_id)


@router.get("/search")
def search_in_inventory(search_key: str, db: Session = Depends(get_db)):
    return InventoryService.search(search_key, db)


@router.delete("/delete_part")
def delete_part_with_id(part_id: int, db: Session = Depends(get_db)):
    InventoryService.delete_part_with_id(part_id, db)
    return {"message": f"Part with ID {part_id} deleted successfully"}


@router.post("/add_file_template")
def add_file_template(coloum_template: FileTemplateAdd, db: Session = Depends(get_db)):
    return FileService.add_file_template(db, coloum_template)


@router.get("/get_available_file_templates")
def get_available_file_templates(db: Session = Depends(get_db)):
    return FileService.get_available_file_templates(db)