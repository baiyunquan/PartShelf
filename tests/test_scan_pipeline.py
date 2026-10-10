"""QR bypass, persisted OCR reuse and catalog identity regressions."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Lock
from time import sleep
from uuid import uuid4

from PIL import Image
import pytest

from app.models import Inventory, Part, ProjectComponentHistory, ProjectPart
from app.services import scan_import_service as service
from tests.test_scan_import import setup, scan
from tests.test_scan_verification import COMPONENT, RAW, evidence


def no_match(lines):
    return {"decision": "no_match", "candidate_components": [], "reasoning": "No match"}


def test_qr_import_bypasses_offline_ocr_and_ai(setup, monkeypatch):
    client, factory, image = setup
    def forbidden(*args, **kwargs):
        pytest.fail("QR import must not call OCR or AI")
    monkeypatch.setattr(service.ocr_client, "recognize_image", forbidden)
    monkeypatch.setattr(service.multi_turn_service, "process", forbidden)
    result = scan(client, image, raw=RAW.replace(COMPONENT["mfr"], "Wrong description")).json()
    assert result["status"] == "imported"
    assert result["ocr"] is None
    with factory() as db:
        assert (db.query(Part).one().library_source, db.query(Part).one().external_part_id) == ("jlcparts", "6119867")
        assert db.query(Inventory).one().quantity_available == 200
        assert db.query(ProjectPart).one().project_id == 1
        assert db.query(ProjectComponentHistory).one().username == "Scanner"


def test_qr_lookup_failure_retry_never_calls_ocr(setup, monkeypatch):
    client, factory, image = setup
    def forbidden(*args):
        pytest.fail("QR retry must only query catalog")
    monkeypatch.setattr(service.ocr_client, "recognize_image", forbidden)
    monkeypatch.setattr(service.multi_turn_service, "process", forbidden)
    monkeypatch.setattr(service, "resolve_component", lambda *args: None)
    result = scan(client, image).json()
    assert result["status"] == "needs_review"
    assert "catalog_unavailable" in result["verification"]["reasons"]
    monkeypatch.setattr(service, "resolve_component", lambda *args: {**COMPONENT, "source": "lcsc_dynamic"})
    retry = client.post(f"/api/scan/{result['id']}/retry").json()
    assert retry["status"] == "imported"
    with factory() as db:
        assert db.query(Part).one().library_source == "jlcparts"


@pytest.mark.parametrize("raw", [RAW.replace(",qty:200", ""), RAW.replace("qty:200", "qty:0")])
def test_jlc_identity_without_valid_quantity_never_falls_through_to_ocr(setup, monkeypatch, raw):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: pytest.fail("No OCR for JLC payload"))
    result = scan(client, image, raw=raw).json()
    assert result["status"] == "needs_review"
    assert "quantity" in result["verification"]["reasons"]
    with factory() as db:
        assert db.query(Part).count() == 0


def test_image_ocr_result_reused_by_retry_and_repeated_upload(setup, monkeypatch):
    client, factory, image = setup
    calls = []
    def ocr(data):
        calls.append(data)
        return evidence("Unknown model", "QTY:2")
    monkeypatch.setattr(service.ocr_client, "recognize_image", ocr)
    monkeypatch.setattr(service.multi_turn_service, "process", no_match)
    first = scan(client, image, raw="").json()
    assert first["status"] == "needs_review"
    client.post(f"/api/scan/{first['id']}/retry")
    second = scan(client, image, raw="").json()
    assert second["ocr"] == first["ocr"]
    assert len(calls) == 1


def test_parallel_same_image_has_one_ocr_invocation(setup, monkeypatch):
    client, factory, image = setup
    calls = []
    lock = Lock()
    def ocr(data):
        with lock:
            calls.append(data)
        sleep(0.2)
        return evidence("Unknown model")
    monkeypatch.setattr(service.ocr_client, "recognize_image", ocr)
    monkeypatch.setattr(service.multi_turn_service, "process", no_match)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scan(client, image, raw="").json(), range(2)))
    assert all(item["status"] == "needs_review" for item in results)
    assert len(calls) == 1


def test_distinct_images_have_distinct_package_fingerprints(setup, monkeypatch):
    client, factory, image = setup
    monkeypatch.setattr(service.multi_turn_service, "process", no_match)
    buffer = BytesIO()
    Image.new("RGB", (300, 200), "black").save(buffer, format="JPEG")
    first = scan(client, image, raw="").json()
    second = scan(client, buffer.getvalue(), raw="").json()
    with factory() as db:
        from app.models import ScanSession
        assert db.get(ScanSession, first["id"]).fingerprint != db.get(ScanSession, second["id"]).fingerprint


def test_failed_ocr_is_not_repeated_by_retry(setup, monkeypatch):
    client, factory, image = setup
    calls = []
    def unavailable(data):
        calls.append(data)
        raise RuntimeError("offline")
    monkeypatch.setattr(service.ocr_client, "recognize_image", unavailable)
    monkeypatch.setattr(service.multi_turn_service, "process", no_match)
    first = scan(client, image, raw="").json()
    retry = client.post(f"/api/scan/{first['id']}/retry").json()
    assert "ocr_unavailable" in retry["verification"]["reasons"]
    assert len(calls) == 1


def test_explicit_altium_confirmation_does_not_resolve_id_as_c_code(setup, monkeypatch):
    client, factory, image = setup
    candidate = {"library_source": "altium", "external_part_id": "31355", "name": "RC0402FR-074K7L",
                 "mfr_part_number": "RC0402FR-074K7L", "package": "0402",
                 "raw_item": {"id": 31355, "lib_reference": "RC0402FR-074K7L", "package": "0402"}}
    monkeypatch.setattr(service.multi_turn_service, "process", lambda _: {
        "decision": "ambiguous", "candidate_components": [candidate]})
    monkeypatch.setattr(service.libraries, "get_altium_component", lambda *args: candidate["raw_item"])
    record = scan(client, image, raw="").json()
    monkeypatch.setattr(service, "resolve_component", lambda *args: pytest.fail("Altium ID is not an LCSC number"))
    response = client.post(f"/api/scan/{record['id']}/confirm", json={
        "library_source": "altium", "external_part_id": "31355", "quantity": 100})
    assert response.status_code == 200
    assert response.json()["status"] == "imported"
    with factory() as db:
        assert (db.query(Part).one().library_source, db.query(Part).one().external_part_id) == ("altium", "31355")


def test_multiple_jlc_qr_payloads_create_review_without_ocr_or_stock(setup, monkeypatch):
    import json
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: pytest.fail("No OCR for multiple JLC QRs"))
    response = client.post("/api/scan/recognize", data={"request_id": str(uuid4()), "qr_texts": json.dumps([
        RAW, RAW.replace("C6119867", "C541722")]), "project_id": "1"}, files={"image": ("label.jpg", image)})
    assert response.status_code == 200
    assert "multiple_labels" in response.json()["verification"]["reasons"]
    with factory() as db:
        assert db.query(Part).count() == 0


def test_failed_history_write_rolls_back_stock_and_project(setup, monkeypatch):
    from sqlalchemy import event
    client, factory, image = setup
    def fail(*args):
        raise RuntimeError("history write failed")
    event.listen(ProjectComponentHistory, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="history write failed"):
            scan(client, image)
        with factory() as db:
            assert db.query(Part).count() == db.query(Inventory).count() == db.query(ProjectPart).count() == 0
    finally:
        event.remove(ProjectComponentHistory, "before_insert", fail)


def test_abandoned_ocr_claim_becomes_terminal_without_another_recognition(setup, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.models import ScanOCRResult
    client, factory, image = setup
    monkeypatch.setattr(service.multi_turn_service, "process", no_match)
    scan(client, image, raw="")
    with factory() as db:
        row = db.query(ScanOCRResult).one()
        row.status, row.result = "processing", None
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        db.commit()
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: pytest.fail("An interrupted attempt must not be rerun"))
    result = scan(client, image, raw="").json()
    assert result["status"] == "needs_review"
    assert "ocr_interrupted" in result["verification"]["reasons"]
    with factory() as db:
        assert db.query(ScanOCRResult).one().status == "complete"
