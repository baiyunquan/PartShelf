from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.i18n import get_current_language
from app.services.warehouse_service import WarehouseService
from db.database import get_db


router = APIRouter()


@router.get("/contents")
def get_warehouse_contents(request: Request, db: Session = Depends(get_db)):
    return WarehouseService.get_contents(db, lang=get_current_language(request))


@router.get("/parts/{part_id}/photo")
def get_warehouse_part_photo(part_id: int, db: Session = Depends(get_db)):
    placement = WarehouseService.get_photo(db, part_id)
    if placement is None:
        raise HTTPException(status_code=404, detail="Warehouse photo not found")
    return Response(content=placement.photo_data, media_type=placement.photo_mime_type)
