import pytest
import re
from fastapi.testclient import TestClient
from app.main import app
from app.services import external_library_service as lib_svc

client = TestClient(app)


def test_fasteners_status():
    status = lib_svc.get_libraries_status()
    assert "fasteners" in status
    assert status["fasteners"]["available"] is True
    assert status["fasteners"]["count"] >= 200
    assert status["fasteners"]["tables_count"] >= 500


def test_fasteners_categories_and_authorities():
    cats = lib_svc.get_fastener_categories()
    assert len(cats) >= 10
    cat_names = [c["group"] for c in cats]
    assert "Hexagon Socket" in cat_names or "Nuts" in cat_names

    auths = lib_svc.get_fastener_authorities()
    assert len(auths) >= 4
    auth_names = [a["authority"] for a in auths]
    assert "ISO" in auth_names
    assert "DIN" in auth_names


def test_fasteners_query():
    # 1. Search ISO4762
    res = lib_svc.query_fasteners(page=1, page_size=10, query="ISO4762")
    assert res["total"] >= 1
    assert any(item["standard_code"] == "ISO4762" for item in res["items"])

    # 2. Search PCB spacer
    res_pcb = lib_svc.query_fasteners(page=1, page_size=10, query="PCBSpacer")
    assert res_pcb["total"] >= 1
    assert any(item["standard_code"] == "PCBSpacer" for item in res_pcb["items"])

    # 3. Filter by authority ISO
    res_iso = lib_svc.query_fasteners(page=1, page_size=20, authority="ISO")
    assert res_iso["total"] >= 40
    assert all(item["authority"] == "ISO" for item in res_iso["items"])


def test_fasteners_detail_iso4762():
    detail = lib_svc.get_fastener_detail("ISO4762")
    assert detail is not None
    assert detail["standard"]["standard_code"] == "ISO4762"
    assert len(detail["param_titles"]) > 0
    assert len(detail["param_rows"]) > 0
    # Check that M3 exists
    m3_row = next((r for r in detail["param_rows"] if r["nominal"] == "M3"), None)
    assert m3_row is not None
    # Check M3 tap hole is 2.5mm
    assert detail["tap_holes"].get("M3") == 2.5
    # Check lengths table exists
    assert len(detail["length_rows"]) > 0


def test_fasteners_detail_pcb_spacer():
    detail = lib_svc.get_fastener_detail("PCBSpacer")
    assert detail is not None
    assert detail["standard"]["standard_code"] == "PCBSpacer"
    assert len(detail["param_rows"]) > 0
    assert len(detail["length_rows"]) > 0


def test_fasteners_hole_charts():
    metric_charts = lib_svc.get_fastener_hole_charts("metric_tap_hole")
    assert len(metric_charts) >= 30
    m3_chart = next((c for c in metric_charts if c["nominal_dia"] == "M3"), None)
    assert m3_chart is not None
    assert m3_chart["hole_diameter"] == 2.50


def test_fasteners_web_routes():
    # List page
    res_list = client.get("/libraries/fasteners")
    assert res_list.status_code == 200
    assert "text/html" in res_list.headers["content-type"]
    assert "FreeCAD" in res_list.text

    # Detail page
    res_detail = client.get("/libraries/fasteners/ISO4762")
    assert res_detail.status_code == 200
    assert "text/html" in res_detail.headers["content-type"]
    assert "ISO4762" in res_detail.text


def test_fasteners_api_routes():
    # Status API
    res_stat = client.get("/api/libraries/status")
    assert res_stat.status_code == 200
    assert res_stat.json()["fasteners"]["available"] is True

    # Categories API
    res_cats = client.get("/api/libraries/fasteners/categories")
    assert res_cats.status_code == 200
    assert len(res_cats.json()) > 0

    # Authorities API
    res_auth = client.get("/api/libraries/fasteners/authorities")
    assert res_auth.status_code == 200
    assert len(res_auth.json()) > 0

    # Search API
    res_search = client.get("/api/libraries/fasteners?q=M3")
    assert res_search.status_code == 200
    assert res_search.json()["total"] > 0

    # Detail API
    res_detail = client.get("/api/libraries/fasteners/ISO4762")
    assert res_detail.status_code == 200
    assert res_detail.json()["standard"]["standard_code"] == "ISO4762"


def test_fasteners_global_search():
    # Quick search
    res_quick = client.get("/api/search/quick?q=ISO4762")
    assert res_quick.status_code == 200
    data_quick = res_quick.json()
    assert "fasteners" in data_quick
    assert data_quick["fasteners"]["total"] > 0

    # Aggregate search - all tab
    res_all = client.get("/api/search/aggregate?q=ISO4762&tab=all")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert "fasteners" in data_all["counts"]
    assert data_all["counts"]["fasteners"] > 0

    # Aggregate search - fasteners tab
    res_fasteners = client.get("/api/search/aggregate?q=ISO4762&tab=fasteners")
    assert res_fasteners.status_code == 200
    data_f = res_fasteners.json()
    assert data_f["tab"] == "fasteners"
    assert data_f["total"] > 0


def test_no_emojis_in_fasteners_templates_and_responses():
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\ufe0f]",
        flags=re.UNICODE
    )

    # 1. HTML list page response
    res_list = client.get("/libraries/fasteners")
    assert not emoji_pattern.search(res_list.text), "Emoji found in /libraries/fasteners"

    # 2. HTML detail page response
    res_detail = client.get("/libraries/fasteners/ISO4762")
    assert not emoji_pattern.search(res_detail.text), "Emoji found in /libraries/fasteners/ISO4762"


def test_fasteners_domains():
    # 1. Check domains endpoint
    res = client.get("/api/libraries/fasteners/domains")
    assert res.status_code == 200
    domains = res.json()
    assert len(domains) == 3
    domain_keys = {d["domain"] for d in domains}
    assert "fasteners" in domain_keys
    assert "power_transmission" in domain_keys
    assert "structural_materials" in domain_keys

    # 2. Filter by power transmission
    res_pt = client.get("/api/libraries/fasteners?domain=power_transmission")
    assert res_pt.status_code == 200
    data_pt = res_pt.json()
    assert data_pt["total"] >= 20
    assert all(item["domain"] == "power_transmission" for item in data_pt["items"])

    # 3. Filter by structural materials
    res_sm = client.get("/api/libraries/fasteners?domain=structural_materials")
    assert res_sm.status_code == 200
    data_sm = res_sm.json()
    assert data_sm["total"] >= 15
    assert all(item["domain"] == "structural_materials" for item in data_sm["items"])


def test_fasteners_assembly_guide():
    # 1. API endpoint for all guides
    res = client.get("/api/libraries/fasteners/assembly-guide")
    assert res.status_code == 200
    guides = res.json()
    assert len(guides) >= 20

    # 2. Check M8 guide specs
    m8_res = client.get("/api/libraries/fasteners/assembly-guide?nominal=M8")
    assert m8_res.status_code == 200
    m8_guides = m8_res.json()
    assert len(m8_guides) == 1
    m8 = m8_guides[0]
    assert m8["nominal"] == "M8"
    assert m8["stress_area"] == 36.6
    assert m8["hex_wrench_af"] == 13.0
    assert m8["hex_key"] == 6.0
    assert m8["dry_torque_8_8"] == 26.2
    assert m8["dry_torque_10_9"] == 38.5
    assert m8["dry_torque_12_9"] == 45.1

    # 3. Check ISO4762 detail includes assembly_guides with is_current
    detail = lib_svc.get_fastener_detail("ISO4762")
    assert "assembly_guides" in detail
    assert len(detail["assembly_guides"]) > 0
    curr_guides = [g for g in detail["assembly_guides"] if g.get("is_current")]
    assert len(curr_guides) >= 10  # M3, M4, M5, M6, M8, M10, etc.

    # 4. Detail page HTML contains assembly guide elements
    res_html = client.get("/libraries/fasteners/ISO4762")
    assert res_html.status_code == 200
    assert "assemblyGuideCard" in res_html.text
    assert "torqueTable" in res_html.text
    assert "wrenchTable" in res_html.text

