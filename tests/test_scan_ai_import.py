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
from app.models.scan_session import ScanSession
from app.services import scan_import_service as service
from app.services.multi_turn_search_service import MultiTurnSearchService
from app.user_identity import SESSION_USERNAME_KEY
from db.database import Base, get_db
from tests.test_scan_verification import COMPONENT, RAW, evidence


@pytest.fixture
def scan_setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scan_ai.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([
            Project(id=1, name="Receiver board"),
            Project(id=3, name="Loose Parts", system_key="loose_parts"),
        ])
        db.commit()

    def dependency():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Scanner"
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/scan")
    app.dependency_overrides[get_db] = dependency

    # Setup mock library for multi_turn_service
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
        conn.executemany(
            "INSERT INTO jlc_components (lcsc, mfr, category, subcategory, package, manufacturer, stock, attributes, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (6119867, "CGA0603X7R104K500JT", "Capacitors", "MLCC", "0603", "TDK", 500, json.dumps({}), "100nF 50V 0603"),
                (965815, "0603WAF1002T5E", "Resistors", "Chip Resistor", "0603", "UNI-ROYAL", 2000, json.dumps({}), "10k 1% 0603"),
            ],
        )

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
    ai_service = MultiTurnSearchService()
    monkeypatch.setattr(service, "multi_turn_service", ai_service)
    monkeypatch.setattr(service, "UPLOAD_DIR", tmp_path / "images")
    monkeypatch.setattr(service, "resolve_component", lambda code, lang="zh": COMPONENT.copy() if str(code) == "C6119867" else None)
    monkeypatch.setattr(service.libraries, "resolve_part_summary", lambda *args, **kwargs: {"name": COMPONENT["mfr"]})

    buffer = BytesIO()
    Image.new("RGB", (300, 200), "white").save(buffer, format="JPEG")
    client = TestClient(app)
    yield client, factory, buffer.getvalue()
    engine.dispose()


def test_non_jlc_qr_invokes_ai_matching(scan_setup, monkeypatch):
    """When a barcode or non-JLC QR is scanned with photo, AI service extracts OCR candidates."""
    client, factory, image = scan_setup

    # OCR recognizes non-JLC label lines
    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("UNI-ROYAL", "0603WAF1002T5E", "10K", "0603", "QTY:100"),
    )

    data = {"qr_text": "PLAIN-BARCODE-12345", "request_id": str(uuid4()), "project_id": "1"}
    response = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")})

    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "needs_review"
    assert "ai_decision" in res.get("verification", {})
    verification = res["verification"]
    assert verification["ai_decision"] in ("exact_match", "ambiguous")
    assert len(verification.get("candidates", [])) >= 1
    top = verification["candidates"][0]
    assert top["external_part_id"] == "965815"
    assert top["name"] == "0603WAF1002T5E"


def test_reused_bag_warning_flagged(scan_setup, monkeypatch):
    """When JLC QR is for C6119867 capacitor, but OCR shows a conflicting resistor MPN."""
    client, factory, image = scan_setup

    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("C965815", "0603WAF1002T5E", "10k 0603", "QTY:100"),
    )

    # QR claims C6119867 (TDK capacitor)
    data = {"qr_text": RAW, "request_id": str(uuid4()), "project_id": "1"}
    response = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")})

    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "needs_review"
    verification = res["verification"]
    assert verification.get("reused_bag_warning") is True
    assert "reused_bag_conflict" in verification.get("reasons", [])
    assert len(verification.get("candidates", [])) >= 1


def test_confirm_candidate_from_ai(scan_setup, monkeypatch):
    """Confirming a scan session using an AI candidate code imports the part."""
    client, factory, image = scan_setup

    monkeypatch.setattr(
        service.ocr_client,
        "recognize_image",
        lambda data: evidence("0603WAF1002T5E", "10k 0603"),
    )

    data = {"qr_text": "BARCODE-111", "request_id": str(uuid4()), "project_id": "1"}
    res = client.post("/api/scan/recognize", data=data, files={"image": ("label.jpg", image, "image/jpeg")}).json()
    scan_id = res["id"]

    confirm_res = client.post(
        f"/api/scan/{scan_id}/confirm",
        json={"lcsc_code": "C965815", "quantity": 100},
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["status"] == "imported"

    with factory() as db:
        part = db.query(Part).filter_by(external_part_id="965815").first()
        assert part is not None
        inv = db.query(Inventory).filter_by(part_id=part.id).first()
        assert inv is not None
        assert inv.quantity_available == 100
