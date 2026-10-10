from io import BytesIO
import json
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.scan_api_routes import router
from app.models import Inventory, Part, Project, ProjectPart
from app.models.custom_component import CustomComponent
from app.models.scan_session import ScanSession
from app.services import external_library_service as libraries
from app.services import scan_import_service as service
from app.services.multi_turn_search_service import MultiTurnSearchService
from app.user_identity import SESSION_USERNAME_KEY
from db.database import Base, get_db
from tests.test_scan_verification import evidence


@pytest.fixture
def custom_scan_setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scan_custom.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([
            Project(id=1, name="Custom Device Project"),
            Project(id=3, name="Loose Parts", system_key="loose_parts"),
        ])
        db.commit()

    def dependency():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Engineer"
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/scan")
    app.dependency_overrides[get_db] = dependency

    # Setup empty mock library
    jlc_path = tmp_path / "jlcparts.db"
    with sqlite3.connect(jlc_path) as conn:
        conn.executescript("""
            CREATE TABLE jlc_components (
                lcsc INTEGER PRIMARY KEY, fetched_at INTEGER, present INTEGER,
                sync_seen INTEGER DEFAULT 0, category TEXT, subcategory TEXT,
                mfr TEXT, package TEXT, joints INTEGER, manufacturer TEXT,
                library_type TEXT, preferred INTEGER, last_on_stock INTEGER,
                description TEXT, datasheet TEXT, stock INTEGER, price TEXT,
                attributes TEXT, rohs INTEGER, eccn TEXT, assembly INTEGER,
                assembly_process TEXT, assembly_mode TEXT, website_component_id TEXT,
                attrition TEXT
            );
            CREATE INDEX jlc_package ON jlc_components(package);
            CREATE TABLE lcsc_components (
                lcsc INTEGER PRIMARY KEY, fetched_at INTEGER, manufacturer TEXT,
                attributes TEXT, image TEXT, url_slug TEXT
            );
        """)

    altium_path = tmp_path / "altium_library.db"
    with sqlite3.connect(altium_path) as conn:
        conn.executescript("""
            CREATE TABLE altium_components (
                id INTEGER PRIMARY KEY, lib_reference TEXT, lcsc_part TEXT,
                category TEXT, package TEXT, manufacturer TEXT,
                mfr_part_number TEXT, description TEXT, resistance TEXT,
                capacitance TEXT, inductance TEXT, parameters_json TEXT
            );
        """)

    monkeypatch.setattr(service.libraries, "JLCPARTS_DB_PATH", jlc_path)
    monkeypatch.setattr(service.libraries, "ALTIUM_DB_PATH", altium_path)
    from app.services import lcsc_dynamic_service as dynamic
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda _code: None)
    monkeypatch.setattr(dynamic, "JLCPARTS_DB_PATH", jlc_path)

    ai_service = MultiTurnSearchService(strict_mode=False)
    def offline():
        raise RuntimeError("Offline model boundary for deterministic tests")
    monkeypatch.setattr(ai_service, "get_extractor_client", offline)
    monkeypatch.setattr(ai_service, "get_reranker_client", offline)
    monkeypatch.setattr(service, "multi_turn_service", ai_service)
    monkeypatch.setattr(service, "UPLOAD_DIR", tmp_path / "images")

    buffer = BytesIO()
    Image.new("RGB", (300, 200), "white").save(buffer, format="JPEG")
    client = TestClient(app)
    yield client, factory, buffer.getvalue()
    engine.dispose()


def test_unmatched_scan_generates_recommended_custom_item(custom_scan_setup, monkeypatch):
    """When a scan does not match any catalog items, Stage 1 extraction populates recommended_custom_item."""
    client, factory, image = custom_scan_setup

    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("SPECIAL-IC-999", "DIP-8", "ACME", "QTY:25"),
    )

    data = {"qr_text": "BARCODE-UNMATCHED-1", "request_id": str(uuid4()), "project_id": "1"}
    response = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")})

    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "needs_review"
    verification = res.get("verification", {})
    assert "recommended_custom_item" in verification
    rec = verification["recommended_custom_item"]
    assert rec["name"] == "SPECIAL-IC-999"
    assert "DIP-8" in rec.get("package", "")


def test_confirm_scan_with_custom_item_payload(custom_scan_setup, monkeypatch):
    """Confirming a scan session with library_source='custom' and custom_item creates custom component, part, and inventory."""
    client, factory, image = custom_scan_setup

    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("PROPRIETARY-MCU-V1", "QFN-32", "ACME Corp", "QTY:50"),
    )

    data = {"qr_text": "BARCODE-CUSTOM-PKG", "request_id": str(uuid4()), "project_id": "1"}
    recognize_res = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")}).json()
    scan_id = recognize_res["id"]

    confirm_payload = {
        "library_source": "custom",
        "custom_item": {
            "name": "PROPRIETARY-MCU-V1-REV2",
            "manufacturer": "ACME Semiconductor",
            "package": "QFN-32",
            "part_type": "Microcontroller",
            "description": "32-bit Cortex M4 custom controller",
            "specs": {"voltage_rating": "3.3V", "frequency": "120MHz"},
        },
        "quantity": 50,
        "note": "Prototype lab batch",
    }

    confirm_res = client.post(f"/api/scan/{scan_id}/confirm", json=confirm_payload)
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()

    assert confirm_data["status"] == "imported"
    assert confirm_data["quantity"] == 50
    assert confirm_data["component"]["library_source"] == "custom"
    assert confirm_data["component"]["name"] == "PROPRIETARY-MCU-V1-REV2"

    with factory() as db:
        # Verify custom_components table
        custom_comp = db.query(CustomComponent).filter_by(name="PROPRIETARY-MCU-V1-REV2").first()
        assert custom_comp is not None
        assert custom_comp.manufacturer == "ACME Semiconductor"
        assert custom_comp.package == "QFN-32"
        assert custom_comp.part_type == "Microcontroller"
        assert custom_comp.description == "32-bit Cortex M4 custom controller"
        assert custom_comp.source_scan_id == scan_id
        assert "voltage_rating" in (custom_comp.specs or "")

        # Verify parts table
        part = db.query(Part).filter_by(library_source="custom", external_part_id=str(custom_comp.id)).first()
        assert part is not None
        assert part.note == "Prototype lab batch"

        # Verify inventories table
        inv = db.query(Inventory).filter_by(part_id=part.id).first()
        assert inv is not None
        assert inv.quantity_available == 50

        # Verify project parts table
        proj_part = db.query(ProjectPart).filter_by(project_id=1, part_id=part.id).first()
        assert proj_part is not None
        assert proj_part.quantity_needed == 50


def test_confirm_scan_with_existing_custom_component_id(custom_scan_setup, monkeypatch):
    """Confirming a scan session with library_source='custom' and existing external_part_id imports that component."""
    client, factory, image = custom_scan_setup

    with factory() as db:
        existing_comp = CustomComponent(
            name="EXISTING-CUSTOM-OPAMP",
            manufacturer="Analog Custom",
            package="SOIC-8",
            part_type="Amplifier",
            description="Low-noise custom opamp",
        )
        db.add(existing_comp)
        db.commit()
        existing_id = existing_comp.id

    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("OPAMP", "SOIC-8", "QTY:10"),
    )

    data = {"qr_text": "BARCODE-EXISTING-CUSTOM", "request_id": str(uuid4()), "project_id": "1"}
    recognize_res = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")}).json()
    scan_id = recognize_res["id"]

    confirm_payload = {
        "library_source": "custom",
        "external_part_id": str(existing_id),
        "quantity": 10,
        "note": "Restocking existing custom part",
    }

    confirm_res = client.post(f"/api/scan/{scan_id}/confirm", json=confirm_payload)
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["status"] == "imported"

    with factory() as db:
        part = db.query(Part).filter_by(library_source="custom", external_part_id=str(existing_id)).first()
        assert part is not None
        inv = db.query(Inventory).filter_by(part_id=part.id).first()
        assert inv is not None
        assert inv.quantity_available == 10


def test_custom_item_validation_errors(custom_scan_setup, monkeypatch):
    """Validation errors occur if custom component name is empty or missing identity."""
    client, factory, image = custom_scan_setup

    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("SOME-TEXT", "QTY:5"),
    )

    data = {"qr_text": "BARCODE-ERR", "request_id": str(uuid4())}
    recognize_res = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")}).json()
    scan_id = recognize_res["id"]

    # Empty name in custom_item
    bad_payload = {
        "library_source": "custom",
        "custom_item": {"name": ""},
        "quantity": 5,
    }
    res = client.post(f"/api/scan/{scan_id}/confirm", json=bad_payload)
    assert res.status_code == 422

    # custom library source without custom_item or external_part_id
    bad_payload_2 = {
        "library_source": "custom",
        "quantity": 5,
    }
    res2 = client.post(f"/api/scan/{scan_id}/confirm", json=bad_payload_2)
    assert res2.status_code == 422


def test_external_library_service_resolves_custom_full(custom_scan_setup, monkeypatch):
    """resolve_part_full returns specs, raw_ocr_text, and source_scan_id for custom components."""
    client, factory, image = custom_scan_setup

    with factory() as db:
        comp = CustomComponent(
            name="TEST-SENSOR-MOD",
            manufacturer="SensorTech",
            package="Module",
            part_type="Sensor",
            description="I2C Temperature Sensor",
            specs=json.dumps({"accuracy": "+/-0.1C", "interface": "I2C"}),
            raw_ocr_text="SensorTech TEST-SENSOR-MOD I2C",
            source_scan_id="test-scan-uuid-123",
        )
        db.add(comp)
        db.commit()
        comp_id = comp.id

    import db.database as db_mod
    monkeypatch.setattr(db_mod, "SessionLocal", factory)

    full = libraries.resolve_part_full("custom", str(comp_id))
    assert full["summary"]["name"] == "TEST-SENSOR-MOD"
    assert full["summary"]["manufacturer"] == "SensorTech"
    assert full["external_details"]["specs"]["accuracy"] == "+/-0.1C"
    assert full["external_details"]["raw_ocr_text"] == "SensorTech TEST-SENSOR-MOD I2C"
    assert full["external_details"]["source_scan_id"] == "test-scan-uuid-123"
