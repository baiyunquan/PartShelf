from collections import defaultdict
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
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
from app.models.part import Part
from db.schema_migrations import LOOSE_PARTS_SYSTEM_KEY
from app.i18n import i18n
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
    def get_all_projects(db: Session, lang: str = "zh") -> list[ProjectListItem]:
        projects = get_all_projects(db)
        result = []
        for p in projects:
            if p.system_key == LOOSE_PARTS_SYSTEM_KEY:
                loose_parts = ProjectService._get_loose_parts(db)
                parts_count = len(loose_parts)
                total_available = sum(part.inventory.quantity_available if part.inventory else 0
                                      for part in loose_parts)
                name = i18n.get("projects.loose_parts_name", lang)
            else:
                parts_count = len(p.parts) if p.parts else 0
                total_available = sum(
                    pp.part.inventory.quantity_available
                    for pp in (p.parts or [])
                    if pp.part and pp.part.inventory
                )
                name = p.name
            result.append(ProjectListItem(
                id=p.id,
                name=name,
                description=p.description,
                parts_count=parts_count,
                system_key=p.system_key,
                is_system=bool(p.system_key),
                total_available_quantity=total_available,
            ))
        return result

    @staticmethod
    def _get_loose_parts(db: Session) -> list[Part]:
        return db.query(Part).options(joinedload(Part.inventory)).filter(
            ~Part.project_parts.any(ProjectPart.project.has(Project.system_key.is_(None)))
        ).order_by(Part.id).all()

    @staticmethod
    def get_project_details(db: Session, project_id: int, lang: str = "zh") -> ProjectDetails:
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )

        is_loose = project.system_key == LOOSE_PARTS_SYSTEM_KEY
        if is_loose:
            parts = ProjectService._get_loose_parts(db)
            project_parts = [(part, 0) for part in parts]
        else:
            project_parts = [
                (pp.part, pp.quantity_needed or 0)
                for pp in get_project_parts_by_project(db, project_id)
                if pp.part
            ]
        part_items = []
        total_available = 0
        for part, required_quantity in project_parts:
            if not part:
                continue
            qty_avail = part.inventory.quantity_available if part.inventory else 0
            total_available += qty_avail
            qty_needed = required_quantity
            shortage = max(0, qty_needed - qty_avail)

            summary = resolve_part_summary(part.library_source, part.external_part_id, lang)
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
            name=(i18n.get("projects.loose_parts_name", lang) if is_loose else project.name),
            description=project.description,
            parts_count=len(part_items),
            system_key=project.system_key,
            is_system=bool(project.system_key),
            total_available_quantity=total_available,
            parts=part_items
        )

    @staticmethod
    def _ensure_regular_project(project: Project) -> None:
        if project.system_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="System projects are read-only",
            )

    @staticmethod
    def update_project(db: Session, project_id: int, project_in: ProjectUpdate) -> Project:
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )
        ProjectService._ensure_regular_project(project)
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
        ProjectService._ensure_regular_project(project)
        delete_project(db, project)

    @staticmethod
    def add_part_to_project(db: Session, project_id: int, part_in: ProjectPartAdd) -> ProjectPart:
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {project_id} not found"
            )
        ProjectService._ensure_regular_project(project)
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
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project with ID {project_id} not found")
        ProjectService._ensure_regular_project(project)
        pp = get_project_part(db, project_id, part_id)
        if not pp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not associated with this project"
            )
        return update_project_part_quantity(db, pp, quantity)

    @staticmethod
    def remove_part_from_project(db: Session, project_id: int, part_id: int):
        project = get_project_by_id(db, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project with ID {project_id} not found")
        ProjectService._ensure_regular_project(project)
        pp = get_project_part(db, project_id, part_id)
        if not pp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Component not associated with this project"
            )
        remove_part_from_project(db, pp)

    @staticmethod
    def get_global_procurement_list(db: Session, lang: str = "zh") -> list[ProcurementItem]:
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

            summary = resolve_part_summary(part.library_source, part.external_part_id, lang)
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
