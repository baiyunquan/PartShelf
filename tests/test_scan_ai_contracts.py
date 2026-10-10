"""Model output must be complete and grounded in the original OCR text."""
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from app.services.multi_turn_search_service import MultiTurnSearchService
from app.services.multi_turn_evaluator import stage1_extract, stage2_rerank
from app.services.multi_turn_retrieval import retrieve_candidates
from paddleocr_vl.adapter import PaddleOCRVLAdapter
from tests.test_scan_import import setup, scan
from tests.test_scan_verification import COMPONENT, evidence
from app.services import scan_import_service as service
from app.models import Inventory, Part


class Completions:
    def __init__(self, value, finish="stop"):
        self.value, self.finish, self.kwargs = value, finish, None
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=self.finish, message=SimpleNamespace(content=json.dumps(self.value)))])


def model_service(completions, strict=True):
    instance = MultiTurnSearchService(strict_mode=strict)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    instance._extractor_client = instance._reranker_client = client
    return instance


def test_extractor_filters_unobserved_model_and_specs():
    completion = Completions({"family": "ic", "queries": [{"kind": "mpn", "text": "PN7160AIHN"},
        {"kind": "mpn", "text": "PN7160A1HN"}], "specs": {"package": "SOT-23", "value": "60V", "manufacturer": "NXP"}, "review_reason": None})
    result = model_service(completion).stage1_extract(["PN7160AIHN", "QTY:3"])
    assert result["queries"] == [{"kind": "mpn", "text": "PN7160AIHN"}]
    assert not result["specs"].get("package")
    assert not result["specs"].get("voltage")
    assert completion.kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize("stage", ["extract", "rerank"])
def test_truncated_json_is_not_accepted_as_exact_match(stage):
    completion = Completions({"decision": "exact_match", "selected_index": 1,
        "family": "general", "queries": [], "specs": {}}, finish="length")
    instance = model_service(completion)
    with pytest.raises(RuntimeError):
        if stage == "extract":
            instance.stage1_extract(["ABC123", "QTY:2"])
        else:
            instance.stage2_rerank({"ocr_text": "ABC123"}, [{"mfr_part_number": "ABC123", "package": "",
                "manufacturer": "", "category": "", "description": ""}])


def test_ordinary_exact_match_uses_explicit_quantity_and_catalog_identity(setup, monkeypatch):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: evidence(COMPONENT["mfr"], "0603", "100nF", "QTY:7"))
    monkeypatch.setattr(service.multi_turn_service, "process", lambda _: {"decision": "exact_match",
        "selected_component": {"library_source": "jlcparts", "external_part_id": "6119867", "raw_item": COMPONENT}})
    result = scan(client, image, raw="").json()
    assert result["status"] == "imported"
    with factory() as db:
        assert db.query(Inventory).one().quantity_available == 7
        assert db.query(Part).one().library_source == "jlcparts"


@pytest.mark.parametrize("lines,reason", [
    ((COMPONENT["mfr"], "0603"), "quantity"),
    (("C6119867", "PN7160A1HN", "0603", "QTY:1"), "model"),
    ((COMPONENT["mfr"], "0805", "QTY:2"), "package"),
    ((COMPONENT["mfr"], "0603", "QTY:2", "QTY:20"), "quantity"),
])
def test_ai_exact_decision_cannot_override_missing_or_conflicting_evidence(setup, monkeypatch, lines, reason):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: evidence(*lines))
    monkeypatch.setattr(service.multi_turn_service, "process", lambda _: {"decision": "exact_match",
        "selected_component": {"library_source": "jlcparts", "external_part_id": "6119867", "raw_item": COMPONENT}})
    result = scan(client, image, raw="").json()
    assert result["status"] == "needs_review"
    assert reason in result["verification"]["reasons"]
    with factory() as db:
        assert db.query(Part).count() == 0


def test_llama_ocr_returns_unknown_confidence_and_truncation(setup, monkeypatch):
    _, _, image = setup
    real_client = httpx.Client
    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "ABC123\nQTY:2"}}]})
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    result = PaddleOCRVLAdapter().recognize(image)
    assert result["status"] == "incomplete"
    assert result["finish_reason"] == "length"
    assert result["lines"][0]["confidence"] is None
    assert result["lines"][0]["box"] is None


def test_full_model_suffix_is_required_by_offline_reranker():
    from app.services.multi_turn_evaluator import rule_based_rerank_fallback
    result = rule_based_rerank_fallback(
        {"extracted_mpn": "PN7160A1HN", "ocr_text": "PN7160A1HN"},
        [{"index": 1, "mfr_part_number": "PN7160", "manufacturer": "NXP", "package": "", "category": "IC", "description": ""}])
    assert result["decision"] == "no_match"


def test_raw_c_number_is_queried_even_when_extractor_omits_it(monkeypatch):
    from app.services import external_library_service as libraries
    instance = model_service(Completions({"family": "general", "queries": [], "specs": {}}))
    looked_up = []
    def lookup(code, *args):
        looked_up.append(code)
        return {"lcsc": 541722, "mfr": "AO3400C", "package": "SOT-23"}
    monkeypatch.setattr(libraries, "get_jlcparts_component", lookup)
    result = instance.process(["AO3400C", "C541722", "SOT-23", "QTY:5"])
    assert result["decision"] == "exact_match"
    assert result["selected_component"]["external_part_id"] == "541722"
    assert looked_up == [541722]


def test_cross_library_exact_model_candidates_merge_using_lcsc_identity(tmp_path, monkeypatch):
    from app.services import external_library_service as libraries
    jlc, altium = tmp_path / "jlc.db", tmp_path / "altium.db"
    with sqlite3.connect(jlc) as conn:
        conn.execute("CREATE TABLE jlc_components(lcsc INTEGER PRIMARY KEY,mfr TEXT,package TEXT,manufacturer TEXT)")
        conn.execute("INSERT INTO jlc_components VALUES(14858,'CL10C101JB8NNNC','0603','Samsung')")
    with sqlite3.connect(altium) as conn:
        conn.execute("CREATE TABLE altium_components(id INTEGER PRIMARY KEY,lib_reference TEXT,mfr_part_number TEXT,lcsc_part TEXT,package TEXT,manufacturer TEXT)")
        conn.executemany("INSERT INTO altium_components VALUES(?,?,?,?,?,?)", [
            (54, "CL10C101JB8NNNC", "CL10C101JB8NNNC", "C14858", "0603", "Samsung"),
            (78287, "CL10C101JB8NNNC", "CL10C101JB8NNNC", "C14858", "0603", "Samsung")])
    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", jlc)
    monkeypatch.setattr(libraries, "ALTIUM_DB_PATH", altium)
    candidates = retrieve_candidates("CL10C101JB8NNNC")
    assert len(candidates) == 1
    assert (candidates[0]["library_source"], candidates[0]["external_part_id"]) == ("jlcparts", "14858")


def test_wrong_catalog_manufacturer_cannot_be_imported_automatically(setup, monkeypatch):
    client, factory, image = setup
    row = {**COMPONENT, "manufacturer": "UNI-ROYAL"}
    monkeypatch.setattr(service, "resolve_component", lambda *args: row)
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: evidence("YAGEO", COMPONENT["mfr"], "0603", "QTY:2"))
    monkeypatch.setattr(service.multi_turn_service, "process", lambda _: {"decision": "exact_match",
        "selected_component": {"library_source": "jlcparts", "external_part_id": "6119867", "raw_item": row}})
    result = scan(client, image, raw="").json()
    assert result["status"] == "needs_review"
    assert "manufacturer" in result["verification"]["reasons"]


def test_scan_client_rejects_legacy_pp_ocr_responses(monkeypatch):
    from app.services import paddleocr_client
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "api_version": "1", "lines": [{"text": "ABC123", "confidence": .99}]}))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(RuntimeError, match="llama.cpp"):
        paddleocr_client.recognize_image(b"image")


@pytest.mark.parametrize("text,quantity,verified", [
    ("QTY:1,000", 1000, True), ("QTY:1 000", 1000, True),
    ("QTY:1,0", None, False), ("QTY:1.5", None, False), ("-3个", None, False),
    ("QTY:2e3", None, False), ("QTY:100X", None, False), ("QTY:1,000PCS", 1000, True),
])
def test_complete_quantity_tokens_cannot_be_truncated(text, quantity, verified):
    from app.services.scan_evidence import verify_text
    result = verify_text({"mfr": "AO3400C", "lcsc": 541722, "package": "SOT-23"}, ["AO3400C", "SOT-23", text])
    assert result["verified"] is verified
    assert result["quantity"] == quantity


@pytest.mark.parametrize("model", ["LM358", "NE555", "LM35"])
def test_short_models_conflict_with_an_observed_supplier_code(model):
    from app.services.scan_evidence import verify_text
    result = verify_text({"mfr": "AO3400C", "lcsc": 541722, "package": "SOT-23"}, ["C541722", model, "SOT-23", "QTY:2"])
    assert not result["verified"]
    assert "model" in result["reasons"]


def test_exact_smd_package_with_through_hole_evidence_requires_review():
    from app.services.scan_evidence import verify_text
    result = verify_text({"mfr": "AO3400C", "lcsc": 541722, "package": "SOT-23"}, ["AO3400C", "SOT-23", "Through-hole", "QTY:2"])
    assert not result["verified"]
    assert "package" in result["reasons"]


@pytest.mark.parametrize("line,model,package", [
    ("型号: CC0201 KRX7R8BB472 4.7nF ±10%", "CC0201KRX7R8BB472", "0201"),
    ("型号: CL 10C101JB8NNNC 100PF ±5%", "CL10C101JB8NNNC", "0603"),
    ("型号: RC0402FR-074K7L 4K7±1%", "RC0402FR-074K7L", "0402"),
])
def test_explicit_model_field_excludes_picking_tickets_and_separates_value(line, model, package):
    from app.services.scan_evidence import verify_text
    result = verify_text({"mfr": model, "package": package}, ["A75656", "柜号:15", "B-12-02-12", line, f"封装:{package}", "数量:100"])
    assert result["verified"]
    assert result["quantity"] == 100


def test_reused_bag_quantity_conflict_is_reported_even_without_a_catalog_match(setup, monkeypatch):
    client, factory, image = setup
    monkeypatch.setattr(service.ocr_client, "recognize_image", lambda _: evidence("QTY:20个", "C49247665", "型号:PN7160A1HN", "数量:1PCS"))
    monkeypatch.setattr(service.multi_turn_service, "process", lambda _: {"decision": "no_match"})
    result = scan(client, image, raw="").json()
    assert "quantity" in result["verification"]["reasons"]
    assert not result["verification"]["fields"]["quantity"]["matched"]
    assert result["status"] == "needs_review"


def test_stage1_extract_standalone_function():
    """Verify standalone stage1_extract function behaves deterministically with heuristic fallback."""
    lines = ["型号: CL10C101JB8NNNC", "封装: 0603", "100PF ±5%", "数量: 100PCS"]
    res = stage1_extract(lines, client=None, strict_mode=False)
    assert res["family"] == "general"
    queries = [q["text"] for q in res.get("queries", [])]
    assert "CL10C101JB8NNNC" in queries
    assert res.get("specs", {}).get("package") == "0603"


def test_stage2_rerank_standalone_function():
    """Verify standalone stage2_rerank function handles candidate adjudication with rule-based fallback."""
    ctx = {
        "ocr_text": "型号: NE555P\\n封装: DIP-8",
        "extracted_mpn": "NE555P",
        "extracted_package": "DIP-8",
    }
    cands = [
        {"mfr_part_number": "NE555P", "package": "DIP-8", "manufacturer": "TI", "description": "Timer"},
        {"mfr_part_number": "NE555D", "package": "SOIC-8", "manufacturer": "TI", "description": "Timer SMD"},
    ]
    res = stage2_rerank(ctx, cands, client=None, strict_mode=False)
    assert res["decision"] == "exact_match"
    assert res["selected_index"] == 1
