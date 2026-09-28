from sqlalchemy.orm import Session, joinedload
from app.models.inventory import Inventory
from app.models.package import Package
from app.models.part import Part
from app.models.project_part import ProjectPart
from app.models.project import Project

def get_part_by_name(db: Session, name: str):
    return db.query(Part).filter(Part.name == name).first()

def create_part(db: Session, new_part: Part):
    db.add(new_part)
    db.commit()
    db.refresh(new_part)
    return new_part

def get_all_parts(db: Session, limit = 0):
    query = db.query(Part).options(
        joinedload(Part.manufacturer),
        joinedload(Part.type),
        joinedload(Part.package),
        joinedload(Part.inventory),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    )
    if limit > 0:
        query = query.limit(limit)
    return query.all()

def get_part_by_id(db: Session, id: int):
    return db.query(Part).options(
        joinedload(Part.manufacturer),
        joinedload(Part.type),
        joinedload(Part.package),
        joinedload(Part.inventory),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).filter(Part.id == id).first()

def get_parts_containing_key(db: Session, search_key: str):
    return db.query(Part).options(
        joinedload(Part.manufacturer),
        joinedload(Part.type),
        joinedload(Part.package),
        joinedload(Part.inventory),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).filter(Part.name.ilike(f'%{search_key}%')).all()

def delete_part(db: Session, part_to_delete: Part):
    db.delete(part_to_delete)
    db.commit()