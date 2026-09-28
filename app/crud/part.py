from sqlalchemy.orm import Session, joinedload
from app.models.inventory import Inventory
from app.models.part import Part
from app.models.project_part import ProjectPart
from app.models.project import Project


def create_part(db: Session, new_part: Part) -> Part:
    db.add(new_part)
    db.commit()
    db.refresh(new_part)
    return new_part


def get_all_parts(db: Session, limit: int = 0):
    query = db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).order_by(Part.id.desc())
    if limit > 0:
        query = query.limit(limit)
    return query.all()


def get_part_by_id(db: Session, part_id: int):
    return db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).filter(Part.id == part_id).first()


def get_parts_by_source_and_external_id(db: Session, library_source: str, external_part_id: str):
    return db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).filter(
        Part.library_source == library_source,
        Part.external_part_id == str(external_part_id)
    ).all()


def update_part(db: Session, part: Part) -> Part:
    db.commit()
    db.refresh(part)
    return part


def delete_part(db: Session, part_to_delete: Part):
    db.delete(part_to_delete)
    db.commit()