from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Inventory, Part, Project, ProjectComponentHistory, ProjectPart
from app.schemas.inventory import PartToInventoryAdd
from app.user_identity import SESSION_USERNAME_KEY, normalize_username
from app.services import inventory_service
from app.services.bom_service import execute_bom_import
from db.database import Base, get_db


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTSHELF_TEST_MODE", "true")
    engine = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _create_project_part(db, quantity=3):
    project = Project(name="History Project")
    part = Part(library_source="kicad", external_part_id="HistorySymbol")
    db.add_all([project, part])
    db.flush()
    db.info["project_history_username"] = "Ada"
    project_part = ProjectPart(
        project_id=project.id,
        part_id=part.id,
        quantity_needed=quantity,
    )
    db.add(project_part)
    db.commit()
    return project, part, project_part


def test_username_cookie_is_url_decoded_and_trimmed():
    assert normalize_username("%E5%B0%8F%E6%98%8E") == "小明"
    assert normalize_username("%20Ada%20") == "Ada"
    assert normalize_username("%20") is None


def test_project_part_insert_and_quantity_changes_are_snapshotted(history_db):
    db = history_db
    project, part, project_part = _create_project_part(db)

    first = db.query(ProjectComponentHistory).one()
    assert (first.action, first.quantity_before, first.quantity_after) == ("added", None, 3)
    assert (first.username, first.project_name_snapshot) == ("Ada", "History Project")
    assert (first.part_id, first.part_source_snapshot, first.part_external_id_snapshot) == (
        part.id, "kicad", "HistorySymbol"
    )

    project_part.quantity_needed = 8
    db.commit()
    changes = db.query(ProjectComponentHistory).order_by(ProjectComponentHistory.id).all()
    assert len(changes) == 2
    assert (changes[1].action, changes[1].quantity_before, changes[1].quantity_after) == (
        "quantity_changed", 3, 8
    )

    project_part.quantity_needed = 8
    db.commit()
    assert db.query(ProjectComponentHistory).count() == 2


def test_project_cascade_delete_keeps_a_removal_snapshot(history_db):
    db = history_db
    project, _, _ = _create_project_part(db, quantity=4)

    db.delete(project)
    db.commit()

    records = db.query(ProjectComponentHistory).order_by(ProjectComponentHistory.id).all()
    assert [record.action for record in records] == ["added", "removed"]
    assert records[-1].project_name_snapshot == "History Project"
    assert (records[-1].quantity_before, records[-1].quantity_after) == (4, None)


def test_bom_import_records_created_project_component(history_db):
    db = history_db
    db.info[SESSION_USERNAME_KEY] = "BOM Operator"

    result = execute_bom_import(
        db=db,
        target_type="new",
        project_name="BOM History Project",
        project_description=None,
        existing_project_id=None,
        quantity_strategy="overwrite",
        items=[{
            "row_index": 1,
            "quantity": 5,
            "selected": True,
            "is_custom": True,
            "custom_name": "BOM History Component",
        }],
    )

    record = db.query(ProjectComponentHistory).one()
    assert result["project_id"] == record.project_id
    assert (record.username, record.project_name_snapshot) == (
        "BOM Operator", "BOM History Project"
    )
    assert (record.part_name_snapshot, record.quantity_after) == (
        "BOM History Component", 5
    )


def test_inventory_add_with_project_ids_records_association(history_db, monkeypatch):
    db = history_db
    db.info[SESSION_USERNAME_KEY] = "Inventory Operator"
    project = Project(name="Inventory History Project")
    db.add(project)
    db.commit()
    monkeypatch.setattr(
        inventory_service,
        "resolve_part_summary",
        lambda *_args, **_kwargs: {"name": "Inventory History Component"},
    )

    result = inventory_service.InventoryService.add_part_to_inventory(
        db,
        PartToInventoryAdd(
            library_source="kicad",
            external_part_id="InventoryHistorySymbol",
            project_ids=[project.id],
        ),
    )

    record = db.query(ProjectComponentHistory).one()
    assert result.id == record.part_id
    assert (record.username, record.project_name_snapshot) == (
        "Inventory Operator", "Inventory History Project"
    )
    assert (record.action, record.quantity_after) == ("added", 0)


def test_inventory_add_without_username_fails_before_creating_records(history_db, monkeypatch):
    db = history_db
    monkeypatch.setenv("PARTSHELF_TEST_MODE", "false")
    project = Project(name="Rejected Inventory Project")
    db.add(project)
    db.commit()
    monkeypatch.setattr(
        inventory_service,
        "resolve_part_summary",
        lambda *_args, **_kwargs: {"name": "Rejected Inventory Component"},
    )

    with pytest.raises(HTTPException) as exc_info:
        inventory_service.InventoryService.add_part_to_inventory(
            db,
            PartToInventoryAdd(
                library_source="kicad",
                external_part_id="RejectedInventorySymbol",
                project_ids=[project.id],
            ),
        )

    assert exc_info.value.status_code == 400
    assert db.query(Part).filter_by(external_part_id="RejectedInventorySymbol").count() == 0
    assert db.query(Inventory).count() == 0


def test_part_cascade_delete_keeps_a_removal_snapshot(history_db):
    db = history_db
    _, part, _ = _create_project_part(db, quantity=6)

    db.delete(part)
    db.commit()

    records = db.query(ProjectComponentHistory).order_by(ProjectComponentHistory.id).all()
    assert [record.action for record in records] == ["added", "removed"]
    assert records[-1].part_external_id_snapshot == "HistorySymbol"
    assert (records[-1].quantity_before, records[-1].quantity_after) == (6, None)


def test_missing_username_is_allowed_only_in_test_mode(history_db, monkeypatch):
    db = history_db
    project = Project(name="Anonymous Project")
    part = Part(library_source="kicad", external_part_id="AnonymousSymbol")
    db.add_all([project, part])
    db.commit()
    db.info.pop("project_history_username", None)
    db.add(ProjectPart(project_id=project.id, part_id=part.id, quantity_needed=1))
    db.commit()
    record = db.query(ProjectComponentHistory).one()
    assert record.username is None

    monkeypatch.setenv("PARTSHELF_TEST_MODE", "false")
    second_project = Project(name="Rejected Anonymous Project")
    second_part = Part(library_source="kicad", external_part_id="RejectedSymbol")
    db.add_all([second_project, second_part])
    db.commit()
    db.add(ProjectPart(
        project_id=second_project.id,
        part_id=second_part.id,
        quantity_needed=1,
    ))
    with pytest.raises(HTTPException) as exc_info:
        db.commit()
    assert exc_info.value.status_code == 400
    db.rollback()


def test_history_api_filters_member_and_api_mutations_require_username_outside_test_mode(
    history_db, monkeypatch
):
    from app.api.project_api_routes import router as project_router
    from app.api.web_routes import router as web_router
    from app.api.bom_api_routes import router as bom_router
    from app.api.inventory_api_routes import router as inventory_router
    from app.api.library_api_routes import router as library_router

    db = history_db
    project = Project(name="API History Project")
    part = Part(library_source="kicad", external_part_id="APIHistorySymbol")
    db.add_all([project, part])
    db.commit()
    project_id, part_id = project.id, part.id

    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    api = FastAPI()
    api.include_router(project_router, prefix="/api/projects")
    api.include_router(bom_router, prefix="/api/projects/bom")
    api.include_router(inventory_router, prefix="/api/inventory")
    api.include_router(library_router, prefix="/api/libraries")
    api.include_router(web_router)

    def override_get_db(request: Request):
        session = factory()
        session.info[SESSION_USERNAME_KEY] = normalize_username(request.cookies.get("username"))
        try:
            yield session
        finally:
            session.close()

    api.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("PARTSHELF_TEST_MODE", "false")

    with TestClient(api) as client:
        rejected = client.post(
            f"/api/projects/{project_id}/add_part",
            json={"part_id": part_id, "quantity_needed": 2},
        )
        assert rejected.status_code == 400

        inventory_rejected = client.post(
            "/api/inventory/add_part_to_inventory",
            json={
                "library_source": "kicad",
                "external_part_id": "MustNotCreateWithoutUsername",
                "project_ids": [project_id],
            },
        )
        assert inventory_rejected.status_code == 400
        assert db.query(Part).filter_by(
            external_part_id="MustNotCreateWithoutUsername"
        ).count() == 0

        alternate_inventory_rejected = client.post(
            "/api/libraries/import_to_inventory",
            params={
                "source": "kicad",
                "part_id": "MustNotCreateFromLibraryWithoutUsername",
                "project_ids": project_id,
            },
        )
        assert alternate_inventory_rejected.status_code == 400
        assert db.query(Part).filter_by(
            external_part_id="MustNotCreateFromLibraryWithoutUsername"
        ).count() == 0

        bom_rejected = client.post(
            "/api/projects/bom/import",
            json={
                "target_type": "new",
                "project_name": "Rejected BOM Project",
                "items": [{
                    "row_index": 1,
                    "quantity": 1,
                    "selected": True,
                    "is_custom": True,
                    "custom_name": "Rejected BOM Component",
                }],
            },
        )
        assert bom_rejected.status_code == 400
        assert db.query(Project).filter_by(name="Rejected BOM Project").count() == 0

        client.cookies.set("username", "%E5%BC%A0%E4%B8%89")
        accepted = client.post(
            f"/api/projects/{project_id}/add_part",
            json={"part_id": part_id, "quantity_needed": 2},
        )
        assert accepted.status_code == 200

        filtered = client.get(
            "/api/projects/history",
            params={"username": "张三", "part_id": part_id},
        )
        assert filtered.status_code == 200
        payload = filtered.json()
        assert payload["members"] == ["张三"]
        assert len(payload["items"]) == 1
        assert payload["items"][0]["project_name"] == "API History Project"

        page = client.get("/project-history")
        assert page.status_code == 200
        assert "Project Component History" in page.text or "项目元件历史" in page.text
        assert "/static/js/user_identity.js" in page.text

    assert db.query(ProjectPart).filter_by(project_id=project_id, part_id=part_id).count() == 1
