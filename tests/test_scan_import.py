from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.scan_api_routes import router
from app.models import Inventory, Part, Project, ProjectComponentHistory, ProjectPart
from app.models.scan_session import ScanSession
from app.services import scan_import_service as service
from app.user_identity import SESSION_USERNAME_KEY
from db.database import Base, get_db
from tests.test_scan_verification import COMPONENT, RAW, evidence


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scan.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([Project(id=1, name="Receiver board"), Project(id=2, name="Other board"),
                    Project(id=3, name="Loose Parts", system_key="loose_parts")])
        db.commit()
    def dependency():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Scanner"
            yield db
    app = FastAPI()
    app.include_router(router, prefix="/api/scan")
    app.dependency_overrides[get_db] = dependency
    monkeypatch.setattr(service, "UPLOAD_DIR", tmp_path / "images")
    monkeypatch.setattr(service, "resolve_component", lambda code, lang="zh": COMPONENT.copy())
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867 BD", COMPONENT["mfr"], "0603", "QTY:200个"))
    monkeypatch.setattr(service.libraries, "resolve_part_summary", lambda *args, **kwargs: {"name": COMPONENT["mfr"]})
    buffer = BytesIO()
    Image.new("RGB", (300, 200), "white").save(buffer, format="JPEG")
    client = TestClient(app)
    yield client, factory, buffer.getvalue()
    engine.dispose()


def scan(client, image, raw=RAW, project_id=1, request_id=None):
    data = {"qr_text": raw, "request_id": request_id or str(uuid4())}
    if project_id is not None:
        data["project_id"] = str(project_id)
    return client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")})


def test_verified_scan_automatically_commits_inventory_project_and_history(setup):
    client, factory, image = setup
    response = scan(client, image)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "imported"
    with factory() as db:
        assert db.query(Part).count() == 1
        assert db.query(Inventory).one().quantity_available == 200
        link = db.query(ProjectPart).one()
        assert (link.project_id, link.quantity_needed) == (1, 200)
        history = db.query(ProjectComponentHistory).one()
        assert (history.username, history.project_name_snapshot, history.quantity_after) == ("Scanner", "Receiver board", 200)
    assert client.get(result["image_url"]).status_code == 200


def test_retries_and_repeated_qr_do_not_duplicate_imports(setup):
    client, factory, image = setup
    request_id = str(uuid4())
    first = scan(client, image, request_id=request_id).json()
    assert scan(client, image, request_id=request_id).json()["id"] == first["id"]
    duplicate = scan(client, image).json()
    assert duplicate["status"] == "duplicate"
    with factory() as db:
        assert db.query(Part).count() == db.query(ProjectPart).count() == 1
    reviewed = client.post(f"/api/scan/{duplicate['id']}/confirm", json={
        "lcsc_code": "C6119867", "quantity": 200, "new_package": True,
    })
    assert reviewed.json()["status"] == "imported"
    assert client.post(f"/api/scan/{duplicate['id']}/confirm", json={
        "lcsc_code": "C6119867", "quantity": 200, "new_package": True,
    }).json()["part_id"] == reviewed.json()["part_id"]
    with factory() as db:
        assert db.query(Part).count() == 2


def test_different_packages_with_same_component_are_independent(setup):
    client, factory, image = setup
    assert scan(client, image).json()["status"] == "imported"
    assert scan(client, image, raw=RAW.replace("pdi:187264811", "pdi:187264812"), project_id=2).json()["status"] == "imported"
    with factory() as db:
        assert db.query(Part).count() == 2
        assert [row.project_id for row in db.query(ProjectPart).order_by(ProjectPart.id)] == [1, 2]


def test_ocr_conflict_is_saved_for_review_with_original_project(setup, monkeypatch):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867", COMPONENT["mfr"], "0805"))
    result = scan(client, image).json()
    assert result["status"] == "needs_review"
    assert result["project_id"] == 1
    with factory() as db:
        assert db.query(Part).count() == 0
    assert client.get("/api/scan/history").json()["items"][0]["id"] == result["id"]
    response = client.post(f"/api/scan/{result['id']}/confirm", json={"lcsc_code": "C6119867", "quantity": 150})
    assert response.json()["status"] == "imported"
    with factory() as db:
        assert (db.query(ProjectPart).one().project_id, db.query(Inventory).one().quantity_available) == (1, 150)


def test_service_failure_never_imports_and_system_project_is_rejected(setup, monkeypatch):
    client, factory, image = setup
    def unavailable(data):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(service.ocr_client, "recognize_image", unavailable)
    result = scan(client, image).json()
    assert result["status"] == "needs_review"
    assert "ocr_unavailable" in result["verification"]["reasons"]
    assert scan(client, image, project_id=3).status_code == 400
    with factory() as db:
        assert db.query(Part).count() == 0


def test_inventory_only_scan_has_no_project_link(setup):
    client, factory, image = setup
    assert scan(client, image, project_id=None).json()["status"] == "imported"
    with factory() as db:
        assert db.query(Part).count() == 1
        assert db.query(ProjectPart).count() == 0


def test_deleted_project_blocks_atomic_import_in_manual_review(setup, monkeypatch):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867"))
    result = scan(client, image).json()
    with factory() as db:
        db.query(Project).filter_by(id=1).delete()
        db.commit()
    response = client.post(f"/api/scan/{result['id']}/confirm", json={"lcsc_code": "C6119867", "quantity": 200})
    assert response.status_code == 409
    with factory() as db:
        assert db.query(Part).count() == db.query(Inventory).count() == 0
        assert db.get(ScanSession, result["id"]).status == "needs_review"


def test_parallel_scan_of_same_package_imports_only_once(setup):
    from concurrent.futures import ThreadPoolExecutor
    client, factory, image = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scan(client, image).json(), range(2)))
    assert sorted(item["status"] for item in results) == ["duplicate", "imported"]
    with factory() as db:
        assert db.query(Part).count() == db.query(Inventory).count() == db.query(ProjectPart).count() == 1


def test_retry_uses_saved_photo_and_original_project(setup, monkeypatch):
    client, factory, image = setup
    original = service.ocr_client.recognize_image
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867"))
    result = scan(client, image, project_id=2).json()
    assert result["status"] == "needs_review"
    monkeypatch.setattr(service.ocr_client, "recognize_image", original)
    response = client.post(f"/api/scan/{result['id']}/retry")
    assert response.json()["status"] == "imported"
    with factory() as db:
        assert db.query(ProjectPart).one().project_id == 2


def test_project_id_reuse_cannot_redirect_review_to_a_different_project(setup, monkeypatch):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867"))
    result = scan(client, image).json()
    with factory() as db:
        db.query(Project).filter_by(id=1).delete()
        db.add(Project(id=1, name="Unrelated replacement"))
        db.commit()
    response = client.post(f"/api/scan/{result['id']}/confirm", json={"lcsc_code": "C6119867", "quantity": 200})
    assert response.status_code == 409
    with factory() as db:
        assert db.query(Part).count() == db.query(ProjectPart).count() == 0


def test_overlapping_retry_and_manual_confirm_cannot_import_twice(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from fastapi import HTTPException
    client, factory, image = setup
    original_ocr = service.ocr_client.recognize_image
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867"))
    record = scan(client, image).json()
    monkeypatch.setattr(service.ocr_client, "recognize_image", original_ocr)
    confirm_lookup, allow_confirm, retry_verify, allow_retry = [Event() for _ in range(4)]
    original_verify = service.verify_label
    def lookup(*args):
        if current_thread().name.startswith("confirm"):
            confirm_lookup.set()
            assert allow_confirm.wait(10)
        return COMPONENT.copy()
    def verify(*args):
        retry_verify.set()
        assert allow_retry.wait(10)
        return original_verify(*args)
    monkeypatch.setattr(service, "resolve_component", lookup)
    monkeypatch.setattr(service, "verify_label", verify)
    def run_confirm():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Reviewer"
            try:
                return service.confirm(db, record["id"], "C6119867", 200).part_id
            except HTTPException as exc:
                assert exc.status_code == 409
                return None
    def run_retry():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Scanner"
            return service.retry_scan(db, record["id"]).part_id
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="confirm") as confirmations, ThreadPoolExecutor(max_workers=1, thread_name_prefix="retry") as retries:
        confirmation = confirmations.submit(run_confirm)
        assert confirm_lookup.wait(10)
        retry = retries.submit(run_retry)
        assert retry_verify.wait(10)
        allow_confirm.set()
        confirmation.result(timeout=10)
        allow_retry.set()
        retry.result(timeout=10)
    with factory() as db:
        assert db.query(Part).count() == db.query(Inventory).count() == db.query(ProjectPart).count() == 1
