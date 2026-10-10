from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.i18n import get_current_language
from app.models.scan_session import ScanSession
from app.models.project import Project
from app.services import scan_import_service as service
from db.database import get_db


router = APIRouter()


class ScanConfirmation(BaseModel):
    lcsc_code: str = Field(min_length=1, max_length=64, description="Component LCSC C-code or library identifier")
    quantity: int = Field(ge=1, le=service.MAX_QUANTITY)
    note: str = Field(default="", max_length=500)
    new_package: bool = False


@router.get("/projects")
def scan_project_options(db: Session = Depends(get_db)):
    return [{"id": project.id, "name": project.name, "identity_token": project.identity_token, "is_system": False}
            for project in db.query(Project).filter(Project.system_key.is_(None)).order_by(Project.id).all()]


@router.post("/recognize")
def recognize_label(
    request: Request,
    qr_text: str = Form(""),
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
    scan = service.recognize(db, qr_text, data, pid, req_id, get_current_language(request))
    return service.public_scan(scan)


@router.get("/history")
def get_scan_history(status: str | None = Query(None), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    query = db.query(ScanSession)
    if status:
        query = query.filter(ScanSession.status == status)
    return {"items": [service.public_scan(scan) for scan in query.order_by(ScanSession.created_at.desc()).limit(limit).all()]}


@router.post("/{scan_id}/confirm")
def confirm_scan(scan_id: str, body: ScanConfirmation, request: Request, db: Session = Depends(get_db)):
    scan = service.confirm(db, scan_id, body.lcsc_code, body.quantity, body.note, body.new_package, get_current_language(request))
    return service.public_scan(scan)


@router.post("/{scan_id}/retry")
def retry_scan(scan_id: str, request: Request, db: Session = Depends(get_db)):
    return service.public_scan(service.retry_scan(db, scan_id, get_current_language(request)))


@router.get("/{scan_id}/image")
def get_scan_image(scan_id: str, db: Session = Depends(get_db)):
    scan = service._get(db, scan_id)
    path = service.UPLOAD_DIR / scan.image_filename
    if not path.is_file():
        raise HTTPException(404, "Scan image not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})
