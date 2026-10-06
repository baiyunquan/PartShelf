from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from uuid import uuid4

from app.models import WarehousePlacement  # noqa: F401 - register model metadata
from app.models.project import Project
from app.models.warehouse_drawer import WarehouseDrawer
from app.warehouse_config import get_cabinet_config
from db.database import Base


LOOSE_PARTS_SYSTEM_KEY = "loose_parts"
LOOSE_PARTS_INTERNAL_NAME = "Loose Parts"


def initialize_main_database(engine: Engine) -> None:
    """Create missing tables, add compatible columns, and seed system metadata."""
    inspector = inspect(engine)
    if "projects" in inspector.get_table_names():
        project_columns = {column["name"] for column in inspector.get_columns("projects")}
    else:
        project_columns = set()
    if project_columns and "system_key" not in project_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN system_key VARCHAR(32)"))
    if project_columns and "identity_token" not in project_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN identity_token VARCHAR(36)"))

    # The old table column is added before create_all so its declared unique
    # index can be created on both fresh and upgraded SQLite databases.
    Base.metadata.create_all(bind=engine)
    scan_columns = {column["name"] for column in inspect(engine).get_columns("scan_sessions")}
    if "project_token" not in scan_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE scan_sessions ADD COLUMN project_token VARCHAR(36)"))
    with engine.begin() as connection:
        ids = list(connection.execute(text("SELECT id FROM projects WHERE identity_token IS NULL")))
        for (project_id,) in ids:
            connection.execute(text("UPDATE projects SET identity_token=:token WHERE id=:id AND identity_token IS NULL"),
                               {"token": str(uuid4()), "id": project_id})
    if engine.dialect.name == "mysql":
        from sqlalchemy.dialects.mysql import MEDIUMBLOB, LONGBLOB
        photo_column = next(column for column in inspect(engine).get_columns("warehouse_placements")
                            if column["name"] == "photo_data")
        if not isinstance(photo_column["type"], (MEDIUMBLOB, LONGBLOB)):
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE warehouse_placements MODIFY photo_data MEDIUMBLOB NOT NULL"))
    ensure_loose_parts_project(engine)
    ensure_warehouse_drawers(engine)


def ensure_warehouse_drawers(engine: Engine) -> None:
    """Seed stable identities without changing existing occupancy metadata."""
    values = [
        {"cabinet_id": cabinet["id"], "drawer_code": drawer["code"], "drawer_type": group["typeCode"]}
        for cabinet in get_cabinet_config()
        for group in cabinet["drawerGroups"] for drawer in group["drawers"]
    ]
    if engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        statement = insert(WarehouseDrawer).values(values).on_conflict_do_nothing()
    elif engine.dialect.name == "mysql":
        from sqlalchemy.dialects.mysql import insert
        statement = insert(WarehouseDrawer).values(values)
        statement = statement.on_duplicate_key_update(cabinet_id=statement.inserted.cabinet_id)
    else:
        raise ValueError("Warehouse allocation supports SQLite and MySQL")
    with engine.begin() as connection:
        connection.execute(statement)


def ensure_loose_parts_project(engine: Engine) -> Project:
    with Session(engine) as db:
        project = db.query(Project).filter(
            Project.system_key == LOOSE_PARTS_SYSTEM_KEY
        ).one_or_none()
        if project is None:
            project = Project(
                name=LOOSE_PARTS_INTERNAL_NAME,
                description=None,
                system_key=LOOSE_PARTS_SYSTEM_KEY,
            )
            db.add(project)
            db.commit()
            db.refresh(project)
        return project
