from fastapi import APIRouter, Depends, HTTPException, Request, File, Form, UploadFile, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.i18n import get_current_language
from app.services.warehouse_service import WarehouseService
from db.database import get_db


router = APIRouter()


@router.get("/suggestion")
def preview_warehouse_suggestion(library_source: str, external_part_id: str,
                                 quantity: int = Query(1, ge=0),
                                 drawer_type: str = Query("S", pattern="^[SL]$"),
                                 db: Session = Depends(get_db)):
    return WarehouseService.suggest_component(db, library_source, external_part_id, quantity, drawer_type)


@router.get("/parts/{part_id}/suggestion")
def get_warehouse_suggestion(part_id: int, drawer_type: str = Query("S", pattern="^[SL]$"),
                             db: Session = Depends(get_db)):
    return WarehouseService.suggest(db, part_id, drawer_type)


@router.post("/parts/{part_id}/placement")
def confirm_warehouse_placement(part_id: int, cabinet_id: str = Form(...),
                                      drawer_code: str = Form(...), photo: UploadFile = File(...),
                                      db: Session = Depends(get_db)):
    photo_data = photo.file.read(10 * 1024 * 1024 + 1)
    return WarehouseService.place(db, part_id, cabinet_id, drawer_code, photo_data, photo.content_type)


@router.delete("/parts/{part_id}/placement")
def remove_warehouse_placement(part_id: int, db: Session = Depends(get_db)):
    return WarehouseService.remove(db, part_id)


@router.get("/contents")
def get_warehouse_contents(request: Request, db: Session = Depends(get_db)):
    return WarehouseService.get_contents(db, lang=get_current_language(request))


@router.get("/parts/{part_id}/photo")
def get_warehouse_part_photo(part_id: int, db: Session = Depends(get_db)):
    placement = WarehouseService.get_photo(db, part_id)
    if placement is None:
        raise HTTPException(status_code=404, detail="Warehouse photo not found")
    return Response(content=placement.photo_data, media_type=placement.photo_mime_type)
