from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.scan_api_routes import router as scan_router
from app.api.warehouse_api_routes import router as warehouse_router
from app.api.web_routes import router as web_router
from app.models import Inventory, Part, Project, ScanSession, WarehousePlacement, WarehouseDrawer
from app.services import scan_import_service as service
from app.user_identity import SESSION_USERNAME_KEY
from db.database import Base, get_db
from tests.test_scan_verification import COMPONENT, RAW, evidence


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([
            Project(id=1, name="Main Board"),
            Project(id=2, name="Loose Parts", system_key="loose_parts"),
            WarehouseDrawer(cabinet_id="BOX-000", drawer_code="S-01", drawer_type="S"),
            WarehouseDrawer(cabinet_id="BOX-000", drawer_code="L-01", drawer_type="L"),
        ])
        db.commit()

    def dependency():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Tester"
            yield db

    app = FastAPI()
    app.include_router(web_router)
    app.include_router(scan_router, prefix="/api/scan")
    app.include_router(warehouse_router, prefix="/api/warehouse")
    app.dependency_overrides[get_db] = dependency

    monkeypatch.setattr(service, "UPLOAD_DIR", tmp_path / "images")
    monkeypatch.setattr(service, "resolve_component", lambda code, lang="zh": COMPONENT.copy())
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda data: evidence("C6119867 BD", COMPONENT["mfr"], "0603", "QTY:100个"))
    monkeypatch.setattr(service.libraries, "resolve_part_summary", lambda *args, **kwargs: {"name": COMPONENT["mfr"], "package": "0603", "part_type": "Capacitor"})

    buffer = BytesIO()
    Image.new("RGB", (320, 240), color="blue").save(buffer, format="JPEG")
    image_bytes = buffer.getvalue()

    client = TestClient(app)
    yield client, factory, image_bytes
    engine.dispose()


def test_scan_page_includes_warehouse_modal_and_translations(test_env):
    client, _, _ = test_env
    for lang in ("zh", "en"):
        res = client.get(f"/scan-import?lang={lang}")
        assert res.status_code == 200
        html = res.text
        assert 'id="warehousePlacementModal"' in html
        assert 'id="warehouse-modal-part-info"' in html
        assert 'id="warehouse-modal-target"' in html
        assert 'id="warehouse-modal-photo-preview"' in html
        assert 'id="warehouse-modal-change-photo-btn"' in html
        assert 'id="warehouse-modal-confirm"' in html
        assert 'id="modal-drawer-type-s"' in html
        assert 'id="modal-drawer-type-l"' in html
        # Warehouse i18n keys injected into page_translations
        assert "placement_heading" in html
        assert "drawer_type_small" in html
        assert "placement_target" in html


def test_scan_import_and_direct_warehouse_placement_with_scan_image(test_env):
    client, factory, image_bytes = test_env

    # 1. Perform scan recognize
    req_id = str(uuid4())
    res = client.post(
        "/api/scan/recognize",
        data={"qr_text": RAW, "request_id": req_id, "project_id": "1"},
        files={"image": ("label.jpg", image_bytes, "image/jpeg")},
    )
    assert res.status_code == 200
    scan_data = res.json()
    assert scan_data["status"] == "imported"
    part_id = scan_data["part_id"]
    scan_id = scan_data["id"]
    assert part_id is not None
    assert scan_data["placement"] is None

    # 2. Get warehouse suggestion for this part
    sugg_res = client.get(f"/api/warehouse/parts/{part_id}/suggestion?drawer_type=S")
    assert sugg_res.status_code == 200
    sugg_data = sugg_res.json()
    assert len(sugg_data["candidates"]) > 0
    candidate = sugg_data["candidates"][0]
    assert candidate["cabinet_id"] == "BOX-000"
    assert candidate["drawer_code"] == "S-01"

    # 3. Retrieve scan image directly from scan endpoint
    img_res = client.get(f"/api/scan/{scan_id}/image")
    assert img_res.status_code == 200
    fetched_image = img_res.content
    assert fetched_image == image_bytes

    # 4. Place into warehouse using the fetched scan image
    place_res = client.post(
        f"/api/warehouse/parts/{part_id}/placement",
        data={"cabinet_id": candidate["cabinet_id"], "drawer_code": candidate["drawer_code"]},
        files={"photo": ("scan_label.jpg", fetched_image, "image/jpeg")},
    )
    assert place_res.status_code == 200
    placed_data = place_res.json()
    assert placed_data["part_id"] == part_id
    assert placed_data["cabinet_id"] == "BOX-000"
    assert placed_data["drawer_code"] == "S-01"

    # 5. Verify public_scan in history now reports the placement
    hist_res = client.get("/api/scan/history")
    assert hist_res.status_code == 200
    items = hist_res.json()["items"]
    matched_item = next(item for item in items if item["id"] == scan_id)
    assert matched_item["placement"] == {"cabinet_id": "BOX-000", "drawer_code": "S-01"}
