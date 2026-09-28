from collections import defaultdict
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.crud.project import (
    create_project,
    get_all_projects,
    get_project_by_id,
    update_project,
    delete_project,
)
from app.crud.project_part import (
    add_part_to_project,
    get_all_project_parts_with_details,
    get_project_part,
    get_project_parts_by_project,
    remove_part_from_project,
    update_project_part_quantity,
)
from app.crud.part import get_part_by_id as get_part_by_id_crud
from app.services.external_library_service import resolve_part_summary
from app.models.project import Project
from app.models.project_part import ProjectPart
from app.schemas.project import (
    ProcurementItem,
    ProjectCreate,
    ProjectDetails,
    ProjectListItem,
    ProjectPartAdd,
    ProjectPartItem,
    ProjectRef,
    ProjectUpdate,
)

class ProjectService:
    @staticmethod
    def create_project(db: Session, project_in: ProjectCreate) -> Project:
        new_project = Project(
            name=project_in.name.strip(),
            description=project_in.description.strip() if project_in.description else None
        )
        return create_project(db, new_project)

    @staticmethod
    def get_all_projects(db: Session) -> list[ProjectListItem]:
        projects = get_all_projects(db)
        result = []
        for p in projects:
            parts_count = len(p.parts) if p.parts else 0
            result.append(ProjectListItem(
                id=p.id,
                name=p.name,
                description=p.description,
                parts_count=parts_count
            ))
        return result

    @staticmethod
    def get_project_details(db: Session, project_id: int) -> ProjectDetails:
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )

        project_parts = get_project_parts_by_project(db, project_id)
        part_items = []
        for pp in project_parts:
            part = pp.part
            if not part:
                continue
            qty_avail = part.inventory.quantity_available if part.inventory else 0
            qty_needed = pp.quantity_needed or 0
            shortage = max(0, qty_needed - qty_avail)

            summary = resolve_part_summary(part.library_source, part.external_part_id)
            part_items.append(ProjectPartItem(
                part_id=part.id,
                part_name=summary.get("name") or f"Part #{part.id}",
                manufacturer=summary.get("manufacturer"),
                package=summary.get("package"),
                part_type=summary.get("part_type"),
                quantity_available=qty_avail,
                quantity_needed=qty_needed,
                shortage=shortage
            ))

        return ProjectDetails(
            id=project.id,
            name=project.name,
            description=project.description,
            parts_count=len(part_items),
            parts=part_items
        )

    @staticmethod
    def update_project(db: Session, project_id: int, project_in: ProjectUpdate) -> Project:
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )
        if project_in.name is not None:
            project.name = project_in.name.strip()
        if project_in.description is not None:
            project.description = project_in.description.strip()
        return update_project(db, project)

    @staticmethod
    def delete_project(db: Session, project_id: int):
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )
        delete_project(db, project)

    @staticmethod
    def add_part_to_project(db: Session, project_id: int, part_in: ProjectPartAdd) -> ProjectPart:
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )
        part = get_part_by_id_crud(db, part_in.part_id)
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {part_in.part_id} not found"
            )

        existing = get_project_part(db, project_id, part_in.part_id)
        if existing:
            # Update quantity if already exists
            existing.quantity_needed = (existing.quantity_needed or 0) + (part_in.quantity_needed or 0)
            return update_project_part_quantity(db, existing, existing.quantity_needed)

        pp = ProjectPart(
            project_id=project_id,
            part_id=part_in.part_id,
            quantity_needed=part_in.quantity_needed or 0
        )
        return add_part_to_project(db, pp)

    @staticmethod
    def update_part_quantity(db: Session, project_id: int, part_id: int, quantity: int) -> ProjectPart:
        pp = get_project_part(db, project_id, part_id)
        if not pp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not associated with this project"
            )
        return update_project_part_quantity(db, pp, quantity)

    @staticmethod
    def remove_part_from_project(db: Session, project_id: int, part_id: int):
        pp = get_project_part(db, project_id, part_id)
        if not pp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not associated with this project"
            )
        remove_part_from_project(db, pp)

    @staticmethod
    def get_global_procurement_list(db: Session) -> list[ProcurementItem]:
        all_pps = get_all_project_parts_with_details(db)
        
        # Group by part
        grouped = defaultdict(lambda: {
            "part": None,
            "total_needed": 0,
            "projects": []
        })

        for pp in all_pps:
            part = pp.part
            if not part:
                continue
            entry = grouped[part.id]
            if entry["part"] is None:
                entry["part"] = part
            qty_needed = pp.quantity_needed or 0
            entry["total_needed"] += qty_needed
            if pp.project:
                entry["projects"].append(ProjectRef(
                    id=pp.project.id,
                    name=pp.project.name,
                    quantity_needed=qty_needed
                ))

        result = []
        for part_id, data in grouped.items():
            part = data["part"]
            qty_avail = part.inventory.quantity_available if part.inventory else 0
            total_needed = data["total_needed"]
            shortage = max(0, total_needed - qty_avail)

            summary = resolve_part_summary(part.library_source, part.external_part_id)
            result.append(ProcurementItem(
                part_id=part.id,
                part_name=summary.get("name") or f"Part #{part.id}",
                manufacturer=summary.get("manufacturer"),
                package=summary.get("package"),
                part_type=summary.get("part_type"),
                quantity_available=qty_avail,
                total_needed=total_needed,
                shortage=shortage,
                projects=data["projects"]
            ))

        # Sort: items with shortage first, then by part_name
        result.sort(key=lambda x: (-x.shortage, x.part_name.lower() if x.part_name else ""))
        return result
