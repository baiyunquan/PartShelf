from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from db.database import get_db
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

router = APIRouter()

@router.get("/", response_model=list[ProjectListItem])
def get_all_projects(db: Session = Depends(get_db)):
    return ProjectService.get_all_projects(db)

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
        parts_count=0
    )

@router.get("/procurement/list", response_model=list[ProcurementItem])
def get_global_procurement_list(db: Session = Depends(get_db)):
    return ProjectService.get_global_procurement_list(db)

@router.get("/procurement/project/{project_id}", response_model=list[ProjectPartItem])
def get_project_procurement_list(project_id: int, db: Session = Depends(get_db)):
    details = ProjectService.get_project_details(db, project_id)
    return details.parts

@router.get("/{project_id}", response_model=ProjectDetails)
def get_project_details(project_id: int, db: Session = Depends(get_db)):
    return ProjectService.get_project_details(db, project_id)

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
