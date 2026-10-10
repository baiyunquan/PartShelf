from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.project import Project
from db.reset_main_database import reset_main_database_data
from db.schema_migrations import initialize_main_database


def test_dynamic_jlc_source_alias_migrates_without_changing_component_identity(tmp_path):
    from app.models import Part
    engine = create_engine(f"sqlite:///{tmp_path / 'source_alias.sqlite'}")
    initialize_main_database(engine)
    with Session(engine) as db:
        db.add(Part(library_source="lcsc_dynamic", external_part_id="541722"))
        db.add(Part(library_source="altium", external_part_id="31355"))
        db.commit()
    initialize_main_database(engine)
    initialize_main_database(engine)
    with Session(engine) as db:
        assert [(p.library_source, p.external_part_id) for p in db.query(Part).order_by(Part.id)] == [
            ("jlcparts", "541722"), ("altium", "31355")]
    engine.dispose()


def test_existing_project_table_migrates_and_system_project_seeds_idempotently(tmp_path):
    database_path = tmp_path / "legacy.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(255), "
            "description VARCHAR(255))"
        ))
        connection.execute(text(
            "INSERT INTO projects (id, name, description) VALUES (1, 'Existing Project', 'keep')"
        ))

    initialize_main_database(engine)
    initialize_main_database(engine)
    with Session(engine) as db:
        projects = db.query(Project).order_by(Project.id).all()
        assert [(project.name, project.system_key) for project in projects] == [
            ("Existing Project", None),
            ("Loose Parts", "loose_parts"),
        ]
    engine.dispose()


def test_explicit_reset_clears_business_rows_and_leaves_one_system_project(tmp_path):
    database_path = tmp_path / "reset.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    separate_library_engine = create_engine(f"sqlite:///{tmp_path / 'external_library.sqlite'}")
    initialize_main_database(engine)
    with separate_library_engine.begin() as connection:
        connection.execute(text("CREATE TABLE external_parts (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO external_parts (id) VALUES (7)"))
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO custom_components (name) VALUES ('test')"))
        connection.execute(text(
            "INSERT INTO file_templates (template_type, template_name, manufacturer_column, "
            "part_name_column, package_column, description_column, quantity_column) "
            "VALUES ('test', 'test', 'm', 'p', 'k', 'd', 'q')"
        ))

    removed = reset_main_database_data(engine)
    assert removed["custom_components"] == 1
    assert removed["file_templates"] == 1
    with Session(engine) as db:
        assert db.query(Project).count() == 1
        assert db.query(Project).one().system_key == "loose_parts"
    with separate_library_engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM external_parts")).scalar_one() == 7
    engine.dispose()
    separate_library_engine.dispose()
