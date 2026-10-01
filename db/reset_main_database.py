from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.project import Project
from db.schema_migrations import LOOSE_PARTS_INTERNAL_NAME, LOOSE_PARTS_SYSTEM_KEY, initialize_main_database, ensure_warehouse_drawers
from db.database import Base


def reset_main_database_data(engine: Engine) -> dict[str, int]:
    """Remove every application-table row, then recreate the system project."""
    initialize_main_database(engine)
    removed: dict[str, int] = {}
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            removed[table.name] = connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            connection.execute(delete(table))

    with Session(engine) as db:
        db.add(Project(name=LOOSE_PARTS_INTERNAL_NAME, system_key=LOOSE_PARTS_SYSTEM_KEY))
        db.commit()
    ensure_warehouse_drawers(engine)
    return removed
