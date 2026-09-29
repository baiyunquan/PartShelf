from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import WarehousePlacement  # noqa: F401 - register model metadata
from app.models.project import Project
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

    # The old table column is added before create_all so its declared unique
    # index can be created on both fresh and upgraded SQLite databases.
    Base.metadata.create_all(bind=engine)
    ensure_loose_parts_project(engine)


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
