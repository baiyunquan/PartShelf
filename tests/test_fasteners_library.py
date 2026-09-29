import pytest
import re
import shutil
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


def test_chinese_heat_insert_alias_returns_localized_name_and_source_description():
    result = lib_svc.query_fasteners(query="热熔螺母", page_size=20, domain="fasteners")
    combined = lib_svc.query_fasteners(query="M3 规格 热熔螺母", page_size=20, domain="fasteners")

    item = next((row for row in result["items"] if row["standard_code"] == "IUTHeatInsert"), None)
    assert item is not None
    assert any(row["standard_code"] == "IUTHeatInsert" for row in combined["items"])
    assert item["standard_name_localized"] == "热熔螺母（热熔嵌件）"
    assert "热熔铜螺母" in item["search_aliases"]
    assert item["description"] == "IUT[A/B/C] Heat Staked Metric Insert"


def test_flat_head_alias_returns_countersunk_standards_without_nuts():
    result = lib_svc.query_fasteners(query="平头螺丝", page_size=100, domain="fasteners")
    codes = {row["standard_code"] for row in result["items"]}

    assert {"ISO10642", "ISO2009", "ISO7046"}.issubset(codes)
    assert not any("Nut" in row["description"] for row in result["items"])


def test_append_custom_heat_insert_spec_is_idempotent_and_keeps_source_row(tmp_path, monkeypatch):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    original = lib_svc.get_fastener_detail("IUTHeatInsert")
    source_m3 = next(row for row in original["param_rows"] if row["nominal"] == "M3")
    dimensions = {"Length": 4, "ExtDia": 5.5}

    first = lib_svc.append_fastener_spec("IUTHeatInsert", "M3", dimensions)
    second = lib_svc.append_fastener_spec("IUTHeatInsert", "m3", dimensions)

    assert first["row_key"].startswith("user:M3:")
    assert second["row_key"] == first["row_key"]
    detail = lib_svc.get_fastener_detail("IUTHeatInsert")
    custom_rows = [row for row in detail["param_rows"] if row.get("is_custom")]
    assert len(custom_rows) == 1
    custom = custom_rows[0]
    assert custom["row_key"] == first["row_key"]
    assert custom["nominal"] == "M3"
    assert custom["values"] == [None, 4.0, 5.5, None, None, None]
    assert next(row for row in detail["param_rows"] if row["nominal"] == "M3")["values"] == source_m3["values"]


def test_custom_rows_allow_distinct_geometries_for_same_nominal(tmp_path, monkeypatch):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    first = lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.5})
    second = lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.6})

    assert first["row_key"] != second["row_key"]
    detail = lib_svc.get_fastener_detail("IUTHeatInsert")
    custom = [row for row in detail["param_rows"] if row.get("is_custom") and row["nominal"] == "M3"]
    assert len(custom) == 2


def test_custom_length_is_appended_to_existing_length_table(tmp_path, monkeypatch):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    result = lib_svc.append_fastener_spec("ISO10642", "M3", {"P": 0.5}, length="4.5")
    detail = lib_svc.get_fastener_detail("ISO10642")

    assert result["length_added"] is True
    assert any(row.get("custom_length") == "4.5" and row["is_custom"] for row in detail["length_rows"])


def test_custom_imperial_length_is_normalized_and_stored_in_millimeters(tmp_path, monkeypatch):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    result = lib_svc.append_fastener_spec(
        "ASMEB18.2.1.6", "1/4in", {"P": 20}, length="1 7/8"
    )
    detail = lib_svc.get_fastener_detail("ASMEB18.2.1.6")
    custom_length = next(row for row in detail["length_rows"] if row["row_key"] == result["length_row_key"])

    assert result["length"] == "1.875in"
    assert detail["standard"]["length_unit"] == "in"
    assert custom_length["lengths"] == ["47.625", "47.625"]


@pytest.mark.parametrize("dimensions", [
    {"Length": 4, "ExtDia": 5.5, "SQL": "DROP TABLE fastener_tables"},
    {"Length": 4, "ExtDia": float("inf")},
    {"Length": 0, "ExtDia": 5.5},
    {"Length": None, "ExtDia": 5.5},
])
def test_append_custom_fastener_spec_rejects_unknown_or_invalid_dimensions(tmp_path, monkeypatch, dimensions):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    with pytest.raises(ValueError):
        lib_svc.append_fastener_spec("IUTHeatInsert", "M3", dimensions)


def test_append_custom_fastener_spec_rejects_unknown_standard(tmp_path, monkeypatch):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    with pytest.raises(ValueError, match="standard"):
        lib_svc.append_fastener_spec("does-not-exist", "M3", {"D": 3})


def test_custom_fastener_spec_post_api(tmp_path, monkeypatch):
    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)

    response = client.post("/api/libraries/fasteners/IUTHeatInsert/specs", json={
        "nominal": "M3",
        "dimensions": {"Length": 4, "ExtDia": 5.5},
    })
    assert response.status_code == 200
    assert response.json()["is_custom"] is True
    assert response.json()["row_key"].startswith("user:M3:")

    with_length = client.post("/api/libraries/fasteners/ISO10642/specs", json={
        "nominal": "M3", "dimensions": {"P": 0.5}, "length": 4.5,
    })
    assert with_length.status_code == 200
    assert with_length.json()["length"] == "4.5"

    invalid = client.post("/api/libraries/fasteners/IUTHeatInsert/specs", json={
        "nominal": "M3",
        "dimensions": {"Length": 4, "ExtDia": 5.5, "table_name": "fastener_standards"},
    })
    assert invalid.status_code == 422


@pytest.mark.parametrize(
    ("language", "expected_label"),
    [("zh", "添加自定义规格"), ("en", "Add Custom Specification")],
)
def test_fastener_details_page_has_localized_custom_spec_form(language, expected_label):
    response = client.get(f"/libraries/fasteners/IUTHeatInsert?lang={language}")

    assert response.status_code == 200
    assert 'id="customFastenerSpecForm"' in response.text
    assert expected_label in response.text
    assert "/static/js/libraries_fasteners_details.js" in response.text
    assert "custom_spec_heading" in response.text


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

