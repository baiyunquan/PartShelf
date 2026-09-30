from datetime import timezone
from math import ceil

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from db.database import get_db
from app.models.part import Part
from app.models.project import Project
from app.models.project_component_history import ProjectComponentHistory
from app.schemas.project import (
    ProcurementItem,
    ProjectCreate,
    ProjectDetails,
    ProjectListItem,
    ProjectPartAdd,
    ProjectPartItem,
    ProjectUpdate,
)
from app.services.project_service import ProjectService
from app.i18n import get_current_language

router = APIRouter()


@router.get("/history")
def get_project_component_history(
    username: str | None = Query(None),
    unattributed: bool = Query(False),
    part_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if username and unattributed:
        raise HTTPException(status_code=400, detail="Choose either a member or unattributed history")

    query = db.query(ProjectComponentHistory)
    if username and username.strip():
        query = query.filter(ProjectComponentHistory.username == username.strip())
    elif unattributed:
        query = query.filter(ProjectComponentHistory.username.is_(None))
    if part_id is not None:
        query = query.filter(ProjectComponentHistory.part_id == part_id)

    total = query.count()
    rows = query.order_by(
        ProjectComponentHistory.changed_at.desc(),
        ProjectComponentHistory.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    member_query = db.query(ProjectComponentHistory.username).filter(
        ProjectComponentHistory.username.is_not(None)
    )
    if part_id is not None:
        member_query = member_query.filter(ProjectComponentHistory.part_id == part_id)
    members = [row[0] for row in member_query.distinct()
               .order_by(ProjectComponentHistory.username).all()]
    project_ids = {row.project_id for row in rows if row.project_id is not None}
    part_ids = {row.part_id for row in rows if row.part_id is not None}
    existing_project_ids = set()
    existing_part_ids = set()
    if project_ids:
        existing_project_ids = {
            row[0] for row in db.query(Project.id).filter(Project.id.in_(project_ids)).all()
        }
    if part_ids:
        existing_part_ids = {
            row[0] for row in db.query(Part.id).filter(Part.id.in_(part_ids)).all()
        }

    return {
        "items": [
            {
                "id": row.id,
                "username": row.username,
                "changed_at": row.changed_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                "action": row.action,
                "project_id": row.project_id,
                "project_exists": row.project_id in existing_project_ids,
                "project_name": row.project_name_snapshot,
                "part_id": row.part_id,
                "part_exists": row.part_id in existing_part_ids,
                "part_source": row.part_source_snapshot,
                "part_external_id": row.part_external_id_snapshot,
                "part_name": row.part_name_snapshot,
                "quantity_before": row.quantity_before,
                "quantity_after": row.quantity_after,
            }
            for row in rows
        ],
        "members": members,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size) if total else 0,
    }

@router.get("/", response_model=list[ProjectListItem])
def get_all_projects(request: Request, db: Session = Depends(get_db)):
    return ProjectService.get_all_projects(db, lang=get_current_language(request))

@router.post("/add")
def create_project(
    name: str = Form(...),
    description: str = Form(None),
    db: Session = Depends(get_db)
):
    project_in = ProjectCreate(name=name, description=description)
    ProjectService.create_project(db, project_in)
    return RedirectResponse("/projects", status_code=303)

@router.post("/api_add", response_model=ProjectListItem)
def create_project_api(
    project_in: ProjectCreate,
    db: Session = Depends(get_db)
):
    project = ProjectService.create_project(db, project_in)
    return ProjectListItem(
        id=project.id,
        name=project.name,
        description=project.description,
        parts_count=0,
        system_key=project.system_key,
        is_system=bool(project.system_key),
        total_available_quantity=0,
    )

@router.get("/procurement/list", response_model=list[ProcurementItem])
def get_global_procurement_list(request: Request, db: Session = Depends(get_db)):
    return ProjectService.get_global_procurement_list(db, lang=get_current_language(request))

@router.get("/procurement/project/{project_id}", response_model=list[ProjectPartItem])
def get_project_procurement_list(project_id: int, request: Request, db: Session = Depends(get_db)):
    details = ProjectService.get_project_details(db, project_id, lang=get_current_language(request))
    return details.parts

@router.get("/{project_id}", response_model=ProjectDetails)
def get_project_details(project_id: int, request: Request, db: Session = Depends(get_db)):
    return ProjectService.get_project_details(db, project_id, lang=get_current_language(request))

@router.put("/{project_id}")
def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    db: Session = Depends(get_db)
):
    ProjectService.update_project(db, project_id, project_in)
    return {"message": f"Project {project_id} updated successfully"}

@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    ProjectService.delete_project(db, project_id)
    return {"message": f"Project {project_id} deleted successfully"}

@router.post("/{project_id}/add_part")
def add_part_to_project(
    project_id: int,
    part_in: ProjectPartAdd,
    db: Session = Depends(get_db)
):
    ProjectService.add_part_to_project(db, project_id, part_in)
    return {"message": "Component added to project successfully"}

@router.post("/{project_id}/update_part_quantity")
def update_part_quantity(
    project_id: int,
    part_id: int = Query(...),
    quantity_needed: int = Query(...),
    db: Session = Depends(get_db)
):
    ProjectService.update_part_quantity(db, project_id, part_id, quantity_needed)
    return {"message": "Quantity updated successfully"}

@router.delete("/{project_id}/remove_part/{part_id}")
def remove_part_from_project(
    project_id: int,
    part_id: int,
    db: Session = Depends(get_db)
):
    ProjectService.remove_part_from_project(db, project_id, part_id)
    return {"message": f"Part {part_id} removed from project {project_id}"}
