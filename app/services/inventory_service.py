from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.crud.inventory import create_inventory, get_inventory_by_part_id, update_inventory_quantity
from app.crud.part import create_part, delete_part, get_all_parts, get_part_by_id, update_part
from app.crud.project_part import add_part_to_project, get_project_part
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.project_part import ProjectPart
from app.schemas.inventory import (
    PartDetailsFlatGet,
    PartInventoryFlatGet,
    PartInventoryQuantity,
    PartInventoryQuantityUpdate,
    PartMetaUpdate,
    PartProjectItem,
    PartToInventoryAdd,
)
from app.services.external_library_service import resolve_part_summary, resolve_part_full


class InventoryService:

    @staticmethod
    def add_part_to_inventory(db: Session, part: PartToInventoryAdd) -> PartInventoryFlatGet:
        if part.quantity < 0:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail="Cannot add part with negative quantity"
            )

        src = (part.library_source or "").lower()
        if src not in ("jlcparts", "altium", "kicad", "fasteners", "custom"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid library_source: '{part.library_source}'. Must be 'jlcparts', 'altium', 'kicad', 'fasteners', or 'custom'."
            )

        ext_id = str(part.external_part_id).strip()
        if not ext_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="external_part_id cannot be empty"
            )

        # Validate that the external part exists
        summary = resolve_part_summary(src, ext_id)
        if not summary or summary.get("name", "").startswith("Part #"):
            # Check if really invalid
            full_res = resolve_part_full(src, ext_id)
            if not full_res.get("external_details"):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Component #{ext_id} not found in {src} library."
                )

        # Create Part record (supports multiple records for the same external part if in different locations)
        db_part = Part(
            library_source=src,
            external_part_id=ext_id,
            storage_location=part.storage_location or "Default Storage",
            note=part.note or (part.description or "")
        )
        created_part = create_part(db, db_part)

        # Create Inventory record
        db_inventory = Inventory(
            part_id=created_part.id,
            quantity_available=part.quantity
        )
        create_inventory(db, db_inventory)

        # Link project IDs
        projects_list = []
        if part.project_ids:
            for pid in part.project_ids:
                if pid:
                    existing_pp = get_project_part(db, pid, created_part.id)
                    if not existing_pp:
                        pp = ProjectPart(
                            project_id=pid,
                            part_id=created_part.id,
                            quantity_needed=0
                        )
                        add_part_to_project(db, pp)

        # Re-fetch for clean output
        return InventoryService._map_flat_part(created_part)

    @staticmethod
    def update_inventory_quantity(db: Session, inventory_quantity: PartInventoryQuantityUpdate) -> PartInventoryQuantity:
        db_inventory = get_inventory_by_part_id(db, inventory_quantity.part_id)
        if not db_inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inventory record not found."
            )

        new_quantity = db_inventory.quantity_available + inventory_quantity.quantity
        if new_quantity < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Not enough stock to remove {abs(inventory_quantity.quantity)} items. Available: {db_inventory.quantity_available}"
            )

        db_inventory.quantity_available = new_quantity
        update_inventory_quantity(db, db_inventory)
        return PartInventoryQuantity(updatedQuantity=db_inventory.quantity_available)

    @staticmethod
    def update_part_meta(db: Session, meta_in: PartMetaUpdate) -> PartInventoryFlatGet:
        db_part = get_part_by_id(db, meta_in.part_id)
        if not db_part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Part not found"
            )
        if meta_in.storage_location is not None:
            db_part.storage_location = meta_in.storage_location
        if meta_in.note is not None:
            db_part.note = meta_in.note
        updated = update_part(db, db_part)
        return InventoryService._map_flat_part(updated)

    @staticmethod
    def _map_projects(part: Part) -> List[PartProjectItem]:
        projects = []
        if getattr(part, "project_parts", None):
            for pp in part.project_parts:
                if pp.project:
                    projects.append(PartProjectItem(
                        id=pp.project.id,
                        name=pp.project.name,
                        quantity_needed=pp.quantity_needed or 0
                    ))
        return projects

    @classmethod
    def _map_flat_part(cls, part: Part, lang: str = "zh") -> PartInventoryFlatGet:
        summary = resolve_part_summary(part.library_source, part.external_part_id, lang)
        qty = part.inventory.quantity_available if part.inventory else 0
        return PartInventoryFlatGet(
            id=part.id,
            library_source=part.library_source,
            external_part_id=part.external_part_id,
            name=summary.get("name") or f"Part #{part.id}",
            manufacturer=summary.get("manufacturer"),
            package=summary.get("package"),
            part_type=summary.get("part_type"),
            storage_location=part.storage_location,
            note=part.note,
            quantity=qty,
            image_url=summary.get("image_url"),
            datasheet_url=summary.get("datasheet_url"),
            projects=cls._map_projects(part)
        )

    @classmethod
    def get_parts_inventory_list(cls, db: Session, limit: int = 0, lang: str = "zh") -> List[PartInventoryFlatGet]:
        parts_list = get_all_parts(db, limit=limit)
        return [cls._map_flat_part(part, lang) for part in parts_list]

    @classmethod
    def get_part_by_id(cls, db: Session, part_id: int, lang: str = "zh") -> PartDetailsFlatGet:
        part_found = get_part_by_id(db, part_id)
        if part_found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with id = {part_id} does not exist"
            )

        full_info = resolve_part_full(part_found.library_source, part_found.external_part_id, lang)
        summary = full_info["summary"]
        qty = part_found.inventory.quantity_available if part_found.inventory else 0

        return PartDetailsFlatGet(
            id=part_found.id,
            library_source=part_found.library_source,
            external_part_id=part_found.external_part_id,
            name=summary.get("name") or f"Part #{part_found.id}",
            manufacturer=summary.get("manufacturer"),
            package=summary.get("package"),
            part_type=summary.get("part_type"),
            storage_location=part_found.storage_location,
            note=part_found.note,
            quantity=qty,
            description=summary.get("description"),
            image_url=summary.get("image_url"),
            datasheet_url=summary.get("datasheet_url"),
            projects=cls._map_projects(part_found),
            external_details=full_info.get("external_details")
        )

    @classmethod
    def search(cls, search_key: str, db: Session, lang: str = "zh") -> List[PartInventoryFlatGet]:
        q = (search_key or "").strip().lower()
        if not q:
            return cls.get_parts_inventory_list(db, lang=lang)

        # Get all parts and filter dynamically against hydrated attributes or storage location / note
        all_parts = cls.get_parts_inventory_list(db, lang=lang)
        matched = []
        for p in all_parts:
            text_corpus = f"{p.name} {p.manufacturer or ''} {p.package or ''} {p.part_type or ''} {p.storage_location or ''} {p.note or ''}".lower()
            if q in text_corpus or f"c{p.external_part_id}".lower() == q or str(p.id) == q:
                matched.append(p)
        return matched

    @staticmethod
    def delete_part_with_id(part_id: int, db: Session):
        part_to_delete = get_part_by_id(db, part_id)
        if part_to_delete is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with id = {part_id} does not exist"
            )
        delete_part(db, part_to_delete)
