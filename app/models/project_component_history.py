from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Session

from db.database import Base
from app.user_identity import SESSION_USERNAME_KEY, require_project_history_username


class ProjectComponentHistory(Base):
    __tablename__ = "project_component_history"
    __table_args__ = (
        Index("ix_project_component_history_project_id", "project_id"),
        Index("ix_project_component_history_part_id", "part_id"),
        Index("ix_project_component_history_changed_at", "changed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, nullable=True)
    changed_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    action = Column(String(32), nullable=False)
    project_id = Column(Integer, nullable=True)
    project_name_snapshot = Column(String(255), nullable=True)
    part_id = Column(Integer, nullable=True)
    part_source_snapshot = Column(String(32), nullable=True)
    part_external_id_snapshot = Column(String(64), nullable=True)
    part_name_snapshot = Column(String(512), nullable=True)
    quantity_before = Column(Integer, nullable=True)
    quantity_after = Column(Integer, nullable=True)


def _old_quantity(project_part) -> int | None:
    from sqlalchemy import inspect

    history = inspect(project_part).attrs.quantity_needed.history
    if history.deleted:
        return history.deleted[0]
    return project_part.quantity_needed


def _related(session: Session, project_part, relationship_name: str, model):
    related = getattr(project_part, relationship_name, None)
    if related is not None:
        return related
    related_id = getattr(project_part, f"{relationship_name}_id", None)
    return session.get(model, related_id) if related_id is not None else None


def _part_name_snapshot(session: Session, part) -> str:
    identity = f"{part.library_source}:{part.external_part_id}"
    if part.library_source == "custom" and str(part.external_part_id).isdigit():
        from app.models.custom_component import CustomComponent

        custom = session.get(CustomComponent, int(part.external_part_id))
        if custom and custom.name:
            return custom.name

    try:
        from app.services.external_library_service import resolve_part_summary

        resolved = resolve_part_summary(part.library_source, part.external_part_id, "zh")
        name = (resolved or {}).get("name")
        if name and not str(name).startswith("Part #"):
            return str(name)[:512]
    except Exception:
        pass
    return identity[:512]


def _make_history(session: Session, project_part, action: str, before, after):
    from app.models.part import Part
    from app.models.project import Project

    project = _related(session, project_part, "project", Project)
    part = _related(session, project_part, "part", Part)
    if project is None or part is None:
        return None

    return ProjectComponentHistory(
        username=session.info.get(SESSION_USERNAME_KEY),
        action=action,
        project_id=project_part.project_id or project.id,
        project_name_snapshot=project.name,
        part_id=project_part.part_id or part.id,
        part_source_snapshot=part.library_source,
        part_external_id_snapshot=part.external_part_id,
        part_name_snapshot=_part_name_snapshot(session, part),
        quantity_before=before,
        quantity_after=after,
    )


def _delete_key(project_part):
    return ("row", project_part.id) if project_part.id is not None else ("object", id(project_part))


def _record_project_component_changes(session: Session, flush_context, instances) -> None:
    from sqlalchemy import inspect, or_, select
    from sqlalchemy.orm import joinedload

    from app.models.part import Part
    from app.models.project import Project
    from app.models.project_part import ProjectPart

    new_rows = [row for row in session.new if isinstance(row, ProjectPart)]
    dirty_rows = [row for row in session.dirty if isinstance(row, ProjectPart)]
    deleted_rows = [row for row in session.deleted if isinstance(row, ProjectPart)]

    deleted_projects = [row for row in session.deleted if isinstance(row, Project) and row.id is not None]
    deleted_parts = [row for row in session.deleted if isinstance(row, Part) and row.id is not None]
    project_ids = [row.id for row in deleted_projects]
    part_ids = [row.id for row in deleted_parts]

    cascade_rows = []
    if project_ids or part_ids:
        filters = []
        if project_ids:
            filters.append(ProjectPart.project_id.in_(project_ids))
        if part_ids:
            filters.append(ProjectPart.part_id.in_(part_ids))
        with session.no_autoflush:
            cascade_rows = session.query(ProjectPart).options(
                joinedload(ProjectPart.project),
                joinedload(ProjectPart.part),
            ).filter(or_(*filters)).all()

    delete_snapshots = {}
    for row in [*deleted_rows, *cascade_rows]:
        delete_snapshots.setdefault(_delete_key(row), row)
    deleted_keys = set(delete_snapshots)

    updates = []
    for row in dirty_rows:
        if _delete_key(row) in deleted_keys:
            continue
        quantity_history = inspect(row).attrs.quantity_needed.history
        if quantity_history.has_changes():
            if quantity_history.deleted:
                before = quantity_history.deleted[0]
            else:
                before = session.connection().execute(
                    select(ProjectPart.quantity_needed).where(ProjectPart.id == row.id)
                ).scalar_one_or_none()
            updates.append((row, before, row.quantity_needed))

    quantity_updates = [(row, before, after) for row, before, after in updates if before != after]
    has_changes = bool(new_rows or delete_snapshots or quantity_updates)
    if not has_changes:
        return

    require_project_history_username(session)

    pending_histories = []
    for row in new_rows:
        if _delete_key(row) not in deleted_keys:
            history = _make_history(session, row, "added", None, row.quantity_needed)
            if history is not None:
                pending_histories.append(history)
    for row, before, after in quantity_updates:
        history = _make_history(session, row, "quantity_changed", before, after)
        if history is not None:
            pending_histories.append(history)
    for row in delete_snapshots.values():
        history = _make_history(session, row, "removed", _old_quantity(row), None)
        if history is not None:
            pending_histories.append(history)

    if not pending_histories:
        return

    session.add_all(pending_histories)


from sqlalchemy import event

event.listen(Session, "before_flush", _record_project_component_changes)
