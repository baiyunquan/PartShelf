"""Remaining audit failures: bounded model retries, catalog conflicts and OCR evidence."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import external_library_service as libraries
from app.services.multi_turn_search_service import MultiTurnSearchService
from app.services.multi_turn_retrieval import deduplicate_candidates, format_candidate
from app.services.scan_evidence import verify_text
from tests.test_scan_import import setup


def extraction():
    return {"family": "resistor", "queries": [{"kind": "mpn", "text": "RC0603FR-0710KL"}],
            "specs": {"package": "0603", "value": "10kΩ", "manufacturer": "YAGEO"}, "review_reason": None}


def adjudication():
    return {"decision": "exact_match", "selected_index": 1, "candidate_indices": None,
            "reasoning": "Complete model match", "excluded": []}


class Responses:
    def __init__(self, responses):
        self.responses, self.calls = responses, []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        value, finish = self.responses[min(len(self.calls)-1, len(self.responses)-1)]
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
            message=SimpleNamespace(content=json.dumps(value)))])


def configured(responses, strict=False):
    service = MultiTurnSearchService(strict_mode=strict)
    service._extractor_client = service._reranker_client = SimpleNamespace(chat=SimpleNamespace(completions=responses))
    return service


def candidate():
    return format_candidate({"lcsc": 98220, "mfr": "RC0603FR-0710KL", "package": "0603",
                             "manufacturer": "YAGEO", "description": "10kΩ resistor"}, "jlcparts")


def test_constructor_uses_existing_llama_config_and_strict_default(monkeypatch):
    monkeypatch.setattr(settings, "LLAMA_EXTRACTOR_BASE_URL", "http://example.invalid:8091/v1")
    monkeypatch.setattr(settings, "LLAMA_TIMEOUT_SECONDS", 63)
    monkeypatch.setattr(settings, "LLAMA_STRICT_MODE", True)
    for name in ("STAGE1_EXTRACTOR_URL", "LLAMA_EXTRACTOR_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    service = MultiTurnSearchService()
    assert service.extractor_base_url == "http://example.invalid:8091/v1"
    assert service.timeout == 63
    assert service.strict_mode


@pytest.mark.parametrize("stage", ["extractor", "reranker"])
def test_one_truncated_completion_is_retried_using_the_same_text(stage):
    response = Responses([(extraction() if stage=="extractor" else adjudication(), "length"),
                          (extraction() if stage=="extractor" else adjudication(), "stop")])
    service = configured(response, strict=True)
    if stage == "extractor":
        result = service.stage1_extract(["RC0603FR-0710KL", "0603", "10kΩ", "YAGEO"])
        assert result["queries"][0]["text"] == "RC0603FR-0710KL"
        assert response.calls[0]["max_tokens"] == 512
    else:
        result = service.stage2_rerank({"ocr_text": "RC0603FR-0710KL"}, [candidate()])
        assert result["selected_index"] == 1
    assert len(response.calls) == 2
    assert response.calls[0]["messages"] == response.calls[1]["messages"]
    assert result["stage_status"]["attempts"] == 2


@pytest.mark.parametrize("stage", ["extractor", "reranker"])
def test_truncation_twice_never_becomes_a_heuristic_success(stage):
    response = Responses([(extraction() if stage=="extractor" else adjudication(), "length")])
    service = configured(response, strict=False)
    with pytest.raises(RuntimeError) as error:
        if stage == "extractor":
            service.stage1_extract(["RC0603FR-0710KL"])
        else:
            service.stage2_rerank({"extracted_mpn": "RC0603FR-0710KL"}, [candidate()])
    assert error.value.details["stage"] == stage
    assert error.value.details["code"] == "output_incomplete"
    assert len(response.calls) == 2


def test_reranker_wrong_types_are_rejected_even_with_fallback_enabled():
    wrong = {**adjudication(), "reasoning": ["This is not a string"]}
    with pytest.raises(RuntimeError):
        configured(Responses([(wrong, "stop")])).stage2_rerank({"extracted_mpn": "RC0603FR-0710KL"}, [candidate()])


def test_extraction_has_raw_line_evidence():
    lines = ["型号: RC0603FR-0710KL", "封装:0603", "阻值:10kΩ", "品牌:YAGEO"]
    result = configured(Responses([(extraction(), "stop")]), strict=True).stage1_extract(lines)
    assert result["field_evidence"]["package"] == [{"line_index": 1, "text": "封装:0603"}]
    assert result["field_evidence"]["value"] == [{"line_index": 2, "text": "阻值:10kΩ"}]


def test_cross_library_same_code_but_conflicting_brand_is_not_merged():
    good = candidate()
    bad = format_candidate({"id": 123, "lcsc_part": "C98220", "mfr_part_number": "RC0603FR-0710KL",
                            "manufacturer": "UNI-ROYAL", "package": "0603"}, "altium")
    assert len(deduplicate_candidates([good, bad])) == 2


def test_cross_library_same_code_but_conflicting_value_is_not_merged():
    good = candidate()
    bad = format_candidate({"id": 123, "lcsc_part": "C98220", "mfr_part_number": "RC0603FR-0710KL",
                            "manufacturer": "YAGEO", "package": "0603", "resistance": "20kΩ"}, "altium")
    assert len(deduplicate_candidates([good, bad])) == 2


def test_conflicting_c_code_record_stays_available_for_review(monkeypatch):
    service = MultiTurnSearchService(strict_mode=True)
    monkeypatch.setattr(libraries, "get_jlcparts_component", lambda code: {"lcsc": 541722, "mfr": "AO3400C", "package": "SOT-23"})
    monkeypatch.setattr(service, "stage1_extract", lambda lines: {"queries": [{"kind":"mpn","text":"LM358"}], "specs": {}})
    monkeypatch.setattr(service, "retrieve_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "stage2_rerank", lambda context, candidates: {
        "decision": "no_match", "selected_index": None, "candidate_indices": [], "reasoning": "Model conflict"})
    result = service.process(["C541722", "LM358", "QTY:2"])
    assert result["all_retrieved_candidates"][0]["external_part_id"] == "541722"


def test_empty_candidates_preserve_extractor_status_and_evidence(monkeypatch):
    service = MultiTurnSearchService()
    evidence = {"query:mpn:RC0603FR-0710KL":[{"line_index":0,"text":"RC0603FR-0710KL"}]}
    monkeypatch.setattr(service,"stage1_extract",lambda _: {"queries":[],"specs":{},"field_evidence":evidence,
        "stage_status":{"status":"complete","attempts":1}})
    monkeypatch.setattr(service,"retrieve_candidates",lambda *args,**kwargs: [])
    result = service.process(["RC0603FR-0710KL"])
    assert result["field_evidence"] == evidence
    assert result["stages"]["extractor"]["status"] == "complete"
    assert result["stages"]["reranker"]["status"] == "not_needed"


def test_offline_passive_value_rules_compare_units_and_full_package():
    from app.services.multi_turn_evaluator import rule_based_rerank_fallback
    rows=[{"index":1,"description":"2.7nF capacitor","package":"0603"},
          {"index":2,"description":"12.7nF capacitor","package":"0603"},
          {"index":3,"description":"2.7nF capacitor","package":"060"}]
    result=rule_based_rerank_fallback({"extracted_value":"2700pF","extracted_package":"0603"},rows)
    assert result["selected_index"] == 1


def test_voltage_conflict_is_checked_against_real_catalog_fields():
    result = verify_text({"mfr":"CC0201KRX7R8BB472", "package":"0201", "description":"4.7nF 25V"},
                         ["CC0201KRX7R8BB472", "0201", "4.7nF", "50V", "数量:100"])
    assert not result["verified"]
    assert "specifications" in result["reasons"]


@pytest.mark.parametrize("unit",["V","v"])
def test_voltage_unit_case_cannot_hide_a_conflict(unit):
    result=verify_text({"mfr":"CC0201KRX7R8BB472","package":"0201","description":"4.7nF 25V"},
        ["CC0201KRX7R8BB472","0201","4.7nF",f"50{unit}","数量:100"])
    assert "specifications" in result["reasons"]


@pytest.mark.parametrize("value",["10Ω","10kΩ","10uH"])
def test_conflicting_passive_measurement_kind_requires_review(value):
    result=verify_text({"mfr":"CC0201KRX7R8BB472","package":"0201","description":"4.7nF25V"},
        ["CC0201KRX7R8BB472","0201",value,"数量:100"])
    assert not result["verified"]
    assert "specifications" in result["reasons"]


@pytest.mark.parametrize("brand",["TI","VISHAY"])
def test_standalone_brand_cannot_hide_a_catalog_conflict(brand):
    result=verify_text({"mfr":"RC0603FR-0710KL","package":"0603","manufacturer":"YAGEO"},
        ["RC0603FR-0710KL","0603",brand,"数量:100"])
    assert "manufacturer" in result["reasons"]


@pytest.fixture
def correction_catalog(tmp_path, monkeypatch):
    jlc, altium = tmp_path/'jlc.db', tmp_path/'altium.db'
    with sqlite3.connect(jlc) as db:
        db.execute("CREATE TABLE jlc_components(lcsc INTEGER PRIMARY KEY,mfr TEXT,package TEXT,manufacturer TEXT,category TEXT,description TEXT,attributes TEXT)")
    with sqlite3.connect(altium) as db:
        db.execute("CREATE TABLE altium_components(id INTEGER PRIMARY KEY,lib_reference TEXT,mfr_part_number TEXT,lcsc_part TEXT,package TEXT,manufacturer TEXT,category TEXT,resistance TEXT,description TEXT)")
        db.execute("INSERT INTO altium_components VALUES(43081,'RC0603FR-0710KL','RC0603FR-0710KL','C98220','0603','YAGEO','Resistors','10kΩ','10k resistor')")
    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", jlc)
    monkeypatch.setattr(libraries, "ALTIUM_DB_PATH", altium)
    from app.services import lcsc_dynamic_service as dynamic
    monkeypatch.setattr(dynamic, "JLCPARTS_DB_PATH", jlc)
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda *args:None)
    return jlc, altium


def test_resistor_single_character_ocr_error_recalls_complete_catalog_model(correction_catalog):
    candidates = MultiTurnSearchService().retrieve_candidates("R00603FR-0710KL")
    assert candidates[0]["external_part_id"] == "43081"
    assert candidates[0]["mfr_part_number"] == "RC0603FR-0710KL"


def test_supported_ocr_model_correction_requires_brand_package_and_value():
    from app.services.scan_evidence import verify_text
    row = {"mfr":"RC0603FR-0710KL","manufacturer":"YAGEO","category":"Resistors", "package":"0603","resistance":"10kΩ"}
    result = verify_text(row, ["型号:R00603FR-0710KL 10K±1%", "品牌:YAGEO", "封装:0603", "数量:100"])
    assert result["verified"]
    assert result["model_correction"] == {"observed":"R00603FR-0710KL","canonical":"RC0603FR-0710KL"}
    assert not verify_text(row, ["R00603FR-0710KL", "0603", "数量:100"])["verified"]
    assert not verify_text(row, ["型号:R00603FR-0710KL 20K", "品牌:YAGEO", "0603", "数量:100"])["verified"]


def test_logistics_on_shared_lines_do_not_become_a_second_model():
    row = {"mfr":"RC0603FR-0710KL", "package":"0603"}
    result = verify_text(row, ["A64837 4759797", "型号:RC0603FR-0710KL", "A-84-03-24 批次:129989", "0603", "数量:100"])
    assert result["verified"]


def test_generic_connector_observations_are_grounded_without_a_fabricated_model():
    from app.services import scan_evidence
    result = scan_evidence.connector_observations(["型号:2.54mm / 1*8P / 排座", "封装:直插, P=2.54mm"])
    assert result["pitch_mm"]["value"] == "2.54"
    assert result["pins"]["value"] == 8
    assert result["mounting"]["value"] == "through_hole"
    assert result["pitch_mm"]["evidence"][0]["line_index"] == 0
    assert "manufacturer_part_number" not in result


def test_fpc_contact_side_and_pins_are_extracted_from_label_text():
    from app.services import scan_evidence
    result = scan_evidence.connector_observations(["型号:0.5mm上接/30P-编带", "封装:SMD, P=0.5mm"])
    assert result["pitch_mm"]["value"] == "0.5"
    assert result["pins"]["value"] == 30
    assert result["contact_side"]["value"] == "top"


def test_outline_dimensions_are_not_labeled_as_connector_pitch():
    from app.services.scan_evidence import connector_observations
    assert "pitch_mm" not in connector_observations(["开发板外形尺寸:2.54mm x 30mm"])
    assert connector_observations(["引脚间距:2.54mm"])["pitch_mm"]["value"] == "2.54"


def test_ordinary_model_error_exposes_stage_and_reuses_existing_ocr(setup, monkeypatch):
    from app.services import scan_import_service as scans
    from app.services.multi_turn_schemas import AIStageError
    from tests.test_scan_verification import evidence
    client, _, image = setup
    calls=[]
    def ocr(data):
        calls.append(data)
        return evidence("RC0603FR-0710KL", "0603", "数量:100")
    def fail(lines):
        raise AIStageError("reranker", "output_incomplete", 2, "length")
    monkeypatch.setattr(scans.ocr_client, "recognize_image", ocr)
    monkeypatch.setattr(scans.multi_turn_service, "process", fail)
    from tests.test_scan_import import scan
    first=scan(client,image,raw="").json()
    second=client.post(f"/api/scan/{first['id']}/retry").json()
    assert second["verification"]["stage_errors"] == [{"stage":"reranker","code":"output_incomplete","attempts":2,"finish_reason":"length"}]
    assert second["label"]["qty"] == 100
    assert len(calls) == 1


def test_llama_api_describes_unknown_region_and_confidence_source(setup, monkeypatch):
    import httpx
    from paddleocr_vl.adapter import PaddleOCRVLAdapter
    _, _, image = setup
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request:httpx.Response(200,json={
        "choices":[{"finish_reason":"stop","message":{"content":"RC0603FR-0710KL"}}]}))
    monkeypatch.setattr(httpx,"Client",lambda **kwargs:real_client(transport=transport,**kwargs))
    result=PaddleOCRVLAdapter().recognize(image)
    assert result["region"] is None
    assert result["confidence_source"] == "not_provided_by_model"


def test_ai_cannot_choose_between_identical_models_with_unknown_label_brand(setup, monkeypatch):
    from app.services import scan_import_service as scans
    from tests.test_scan_import import scan
    from tests.test_scan_verification import COMPONENT, evidence
    client, _, image = setup
    first = {"library_source":"jlcparts","external_part_id":"6119867", "raw_item":{**COMPONENT,"manufacturer":"TDK"}}
    other = {"library_source":"altium","external_part_id":"999", "mfr_part_number":COMPONENT["mfr"], "package":"0603", "manufacturer":"YAGEO"}
    monkeypatch.setattr(scans.ocr_client,"recognize_image",lambda _:evidence(COMPONENT["mfr"],"0603","数量:100"))
    monkeypatch.setattr(scans.multi_turn_service,"process",lambda _: {"decision":"exact_match","selected_component":first,"all_retrieved_candidates":[first,other]})
    result=scan(client,image,raw="").json()
    assert result["status"] == "needs_review"
    assert "ambiguous_candidates" in result["verification"]["reasons"]


def test_altium_supplier_reference_fetches_matching_model_and_keeps_conflicting_brand(correction_catalog, monkeypatch):
    _, altium = correction_catalog
    with sqlite3.connect(altium) as db:
        db.execute("UPDATE altium_components SET manufacturer='Uniroyal'")
    calls=[]
    def resolve(code):
        calls.append(code)
        return {"lcsc":98220,"mfr":"RC0603FR-0710KL","manufacturer":"YAGEO","package":"0603","description":"10kΩ resistor"}
    monkeypatch.setattr(libraries,"get_jlcparts_component",resolve)
    candidates=MultiTurnSearchService().retrieve_candidates("R00603FR-0710KL")
    assert calls == [98220]
    assert {(c['library_source'],c['manufacturer']) for c in candidates} == {('jlcparts','YAGEO'),('altium','Uniroyal')}


def test_exact_retrieval_reports_truncated_candidate_pool(correction_catalog):
    _, altium = correction_catalog
    with sqlite3.connect(altium) as db:
        db.execute("INSERT INTO altium_components VALUES(43082,'RC0603FR-0710KL','RC0603FR-0710KL',NULL,'0603','Other Brand','Resistors','10kΩ','10k resistor')")
    rows=MultiTurnSearchService().retrieve_candidates("RC0603FR-0710KL",max_candidates=1)
    assert len(rows) == 1
    assert rows[0]["retrieval_truncated"] is True


def test_truncated_pool_cannot_be_automatically_imported(setup,monkeypatch):
    from app.services import scan_import_service as scans
    from tests.test_scan_import import scan
    from tests.test_scan_verification import COMPONENT,evidence
    client,_,image=setup
    selected={"library_source":"jlcparts","external_part_id":"6119867",
        "raw_item":COMPONENT,"retrieval_truncated":True}
    monkeypatch.setattr(scans.ocr_client,"recognize_image",lambda _:evidence(COMPONENT["mfr"],"0603","数量:100"))
    monkeypatch.setattr(scans.multi_turn_service,"process",lambda _:{"decision":"exact_match",
        "selected_component":selected,"all_retrieved_candidates":[selected]})
    result=scan(client,image,raw="").json()
    assert result["status"] == "needs_review"
    assert "ambiguous_candidates" in result["verification"]["reasons"]


def test_reranker_cannot_select_an_excluded_candidate():
    wrong={**adjudication(),"excluded":[{"index":1,"reason":"Different model"}]}
    with pytest.raises(RuntimeError) as error:
        configured(Responses([(wrong,"stop")])).stage2_rerank({},[candidate()])
    assert error.value.details["code"] == "inconsistent_decision"
