from sqlalchemy.orm import Session, joinedload
from app.models.inventory import Inventory
from app.models.part import Part
from app.models.project_part import ProjectPart
from app.models.project import Project
from app.models.warehouse_placement import WarehousePlacement


def create_part(db: Session, new_part: Part) -> Part:
    db.add(new_part)
    db.commit()
    db.refresh(new_part)
    return new_part


def get_all_parts(db: Session, limit: int = 0):
    query = db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.warehouse_placement),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).order_by(Part.id.desc())
    if limit > 0:
        query = query.limit(limit)
    return query.all()


def get_inventory_parts_by_warehouse_status(db: Session, warehouse_status: str, limit: int = 0):
    query = db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.warehouse_placement),
        joinedload(Part.project_parts).joinedload(ProjectPart.project),
    )
    if warehouse_status == "in_warehouse":
        query = query.join(WarehousePlacement)
    elif warehouse_status == "not_in_warehouse":
        query = query.outerjoin(WarehousePlacement).filter(WarehousePlacement.part_id.is_(None))
    else:
        raise ValueError("warehouse_status must be 'in_warehouse' or 'not_in_warehouse'")
    query = query.order_by(Part.id.desc())
    if limit > 0:
        query = query.limit(limit)
    return query.all()


def get_part_by_id(db: Session, part_id: int):
    return db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.warehouse_placement),
        joinedload(Part.project_parts).joinedload(ProjectPart.project)
    ).filter(Part.id == part_id).first()


def get_parts_by_source_and_external_id(db: Session, library_source: str, external_part_id: str):
    return db.query(Part).options(
        joinedload(Part.inventory),
        joinedload(Part.warehouse_placement),
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
