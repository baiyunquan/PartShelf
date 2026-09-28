from sqlalchemy.orm import Session, joinedload
from app.models.project_part import ProjectPart
from app.models.part import Part
from app.models.project import Project

def get_project_part(db: Session, project_id: int, part_id: int):
    return db.query(ProjectPart).filter(
        ProjectPart.project_id == project_id,
        ProjectPart.part_id == part_id
    ).first()

def add_part_to_project(db: Session, project_part: ProjectPart) -> ProjectPart:
    db.add(project_part)
    db.commit()
    db.refresh(project_part)
    return project_part

def update_project_part_quantity(db: Session, project_part: ProjectPart, quantity: int) -> ProjectPart:
    project_part.quantity_needed = quantity
    db.commit()
    db.refresh(project_part)
    return project_part

def remove_part_from_project(db: Session, project_part: ProjectPart):
    db.delete(project_part)
    db.commit()

def get_project_parts_by_project(db: Session, project_id: int):
    return db.query(ProjectPart).options(
        joinedload(ProjectPart.part).joinedload(Part.inventory)
    ).filter(ProjectPart.project_id == project_id).all()

def get_all_project_parts_with_details(db: Session):
    return db.query(ProjectPart).options(
        joinedload(ProjectPart.project),
        joinedload(ProjectPart.part).joinedload(Part.inventory)
    ).all()
