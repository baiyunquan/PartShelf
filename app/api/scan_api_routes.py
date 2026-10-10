from typing import Any
from uuid import uuid4
import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.i18n import get_current_language
from app.models.scan_session import ScanSession
from app.models.project import Project
from app.services import scan_import_service as service
from db.database import get_db


router = APIRouter()


class CustomItemPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    package: str | None = Field(default=None, max_length=128)
    part_type: str | None = Field(default=None, max_length=128)
    description: str | None = None
    specs: dict[str, Any] | None = None


class ScanConfirmation(BaseModel):
    lcsc_code: str | None = Field(default=None, min_length=1, max_length=64, description="Legacy LCSC C-code")
    library_source: str | None = Field(default=None, pattern="^(jlcparts|altium|kicad|custom)$")
    external_part_id: str | None = Field(default=None, min_length=1, max_length=64)
    custom_item: CustomItemPayload | None = None
    quantity: int = Field(ge=1, le=service.MAX_QUANTITY)
    note: str = Field(default="", max_length=500)
    new_package: bool = False

    @model_validator(mode="after")
    def identity(self):
        if self.library_source == "custom":
            if not self.custom_item and not self.external_part_id:
                raise ValueError("Provide custom_item details or existing custom external_part_id")
            return self
        if bool(self.library_source) != bool(self.external_part_id):
            raise ValueError("Provide both library_source and external_part_id")
        if not self.library_source and not self.lcsc_code:
            raise ValueError("Provide a catalog identity or LCSC C-code")
        return self


@router.get("/projects")
def scan_project_options(db: Session = Depends(get_db)):
    return [{"id": project.id, "name": project.name, "identity_token": project.identity_token, "is_system": False}
            for project in db.query(Project).filter(Project.system_key.is_(None)).order_by(Project.id).all()]


@router.post("/recognize")
def recognize_label(
    request: Request,
    qr_text: str = Form(""),
    qr_texts: str | None = Form(None),
    request_id: str | None = Form(None),
    project_id: str | int | None = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    req_id = str(request_id).strip() if request_id and str(request_id).strip() else str(uuid4())
    pid = None
    if project_id is not None:
        p_str = str(project_id).strip()
        if p_str.isdigit():
            pid = int(p_str)
    data = image.file.read(service.MAX_UPLOAD_BYTES + 1)
    image.file.close()
    payloads = None
    if qr_texts is not None:
        try:
            payloads = json.loads(qr_texts)
            if not isinstance(payloads, list) or len(payloads) > 8 or any(not isinstance(p, str) or len(p) > 4096 for p in payloads):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "qr_texts must be an array of up to eight QR payloads")
    scan = service.recognize(db, qr_text, data, pid, req_id, get_current_language(request), qr_texts=payloads)
    return service.public_scan(scan, db=db)


@router.get("/history")
def get_scan_history(status: str | None = Query(None), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    query = db.query(ScanSession)
    if status:
        query = query.filter(ScanSession.status == status)
    return {"items": [service.public_scan(scan, db=db) for scan in query.order_by(ScanSession.created_at.desc()).limit(limit).all()]}


@router.post("/{scan_id}/confirm")
def confirm_scan(scan_id: str, body: ScanConfirmation, request: Request, db: Session = Depends(get_db)):
    custom_dict = body.custom_item.model_dump() if body.custom_item else None
    scan = service.confirm(db, scan_id, body.lcsc_code, body.quantity, body.note, body.new_package,
                           get_current_language(request), body.library_source, body.external_part_id,
                           custom_item=custom_dict)
    return service.public_scan(scan, db=db)


@router.post("/{scan_id}/retry")
def retry_scan(scan_id: str, request: Request, db: Session = Depends(get_db)):
    return service.public_scan(service.retry_scan(db, scan_id, get_current_language(request)), db=db)


@router.get("/{scan_id}/image")
def get_scan_image(scan_id: str, db: Session = Depends(get_db)):
    scan = service._get(db, scan_id)
    path = service.UPLOAD_DIR / scan.image_filename
    if not path.is_file():
        raise HTTPException(404, "Scan image not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})
