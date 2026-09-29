"""One-time reset of the repository's local main SQLite database."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import create_engine, inspect, select, func
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register every application table
from db.database import Base
from db.reset_main_database import reset_main_database_data
from db.schema_migrations import LOOSE_PARTS_SYSTEM_KEY


MAIN_DATABASE = BASE_DIR / "partshelf.db"
RESET_MARKER = BASE_DIR / ".main_database_test_reset.done"


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear local main database test records once.")
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="Required explicit confirmation; this deletes every row in partshelf.db.",
    )
    args = parser.parse_args()
    if not args.confirm_reset:
        parser.error("pass --confirm-reset to clear the local main database")
    if RESET_MARKER.exists():
        parser.error(f"this one-time reset was already recorded at {RESET_MARKER}")
    if not MAIN_DATABASE.is_file():
        parser.error(f"main database file does not exist: {MAIN_DATABASE}")

    engine = create_engine(f"sqlite:///{MAIN_DATABASE.as_posix()}")
    if inspect(engine).get_table_names() == []:
        parser.error(f"database has no application schema: {MAIN_DATABASE}")

    print(f"Reset target: {MAIN_DATABASE}")
    removed = reset_main_database_data(engine)
    for table_name, row_count in sorted(removed.items()):
        print(f"{table_name}: removed {row_count}")
    with Session(engine) as db:
        projects = db.execute(select(func.count()).select_from(Base.metadata.tables["projects"]).where(
            Base.metadata.tables["projects"].c.system_key == LOOSE_PARTS_SYSTEM_KEY
        )).scalar_one()
    print(f"System projects after reset: {projects}")
    engine.dispose()
    RESET_MARKER.write_text(
        f"Reset completed at {datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
