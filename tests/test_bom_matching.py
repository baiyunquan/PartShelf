import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services import external_library_service as libraries
from app.services import lcsc_dynamic_service as dynamic
from app.services.bom_service import analyze_bom_matching, execute_bom_import, parse_bom_file
from app.services.bom_matcher import candidate_conflicts, measurement
from db.database import Base
from db.database import SessionLocal
from app.models.project import Project
from app.models.part import Part
from app.models.inventory import Inventory
from app.api.bom_api_routes import BomImportItem
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def matching_databases(tmp_path, monkeypatch):
    # Keep unmatched-code tests offline and deterministic. Tests for dynamic
    # lookup replace this fetcher with their own simulated LCSC response.
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda _code: None)
    jlc_path = tmp_path / "jlcparts.db"
    altium_path = tmp_path / "altium_library.db"
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
                (100001, "CAP-27-A", "Capacitors", "MLCC", "0603", "M1", 0, json.dumps({"Capacitance": "27pF"}), "27pF"),
                (100002, "CAP-27-B", "Capacitors", "MLCC", "0603", "M2", 20, json.dumps({"Capacitance": "27pF", "Voltage Rating": "25V", "Tolerance": "±10%"}), "27pF"),
                (100003, "CAP-27-C", "Capacitors", "MLCC", "0402", "M3", 99, json.dumps({"Capacitance": "27pF"}), "27pF"),
                (100004, "CAP-220", "Capacitors", "MLCC", "0603", "M4", 5, json.dumps({"Capacitance": "220pF"}), "220pF"),
                (100005, "IND-1U5", "Inductors, Coils, Chokes", "Power Inductors", "1008", "M5", 0, json.dumps({"Inductance": "1.5uH"}), "1.5uH"),
                (100006, "XTAL-24", "Crystals, Oscillators, Resonators", "Crystals", "SMD3225-4P", "M6", 8, json.dumps({"Frequency": "24MHz"}), "24MHz"),
                (100007, "LED-GREEN", "Optoelectronics", "LED Indication", "0603", "M7", 3, json.dumps({"Illumination Color": "Green"}), "Green LED"),
            ],
        )
    with sqlite3.connect(altium_path) as conn:
        conn.executescript("""
            CREATE TABLE altium_components (
                id INTEGER PRIMARY KEY, lib_reference TEXT, lcsc_part TEXT,
                category TEXT, package TEXT, manufacturer TEXT,
                mfr_part_number TEXT, description TEXT, resistance TEXT,
                capacitance TEXT, inductance TEXT, parameters_json TEXT,
                basic_part INTEGER, tolerance TEXT, voltage_rating TEXT,
                power_rating TEXT, datasheet_url TEXT, jlcpcb_url TEXT,
                lcsc_url TEXT, source_file TEXT
            );
            CREATE INDEX altium_code ON altium_components(lcsc_part);
        """)
        conn.executemany(
            "INSERT INTO altium_components (id,lib_reference,lcsc_part,category,package,manufacturer,mfr_part_number,description,resistance,capacitance,inductance,parameters_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "CAP-10U", "777001", "Capacitors - MLCC", "0603", "M8", "CAP-10U", "", "", "10000000pF", "", "{}"),
                (2, "CAP-220-0402", "C777002", "Capacitors - MLCC", "0402", "M9", "CAP-220-0402", "", "", "220pF", "", "{}"),
                (3, "CGA0603X7R104K500JT", "C777003", "Capacitors - MLCC", "0603", "M10", "CGA0603X7R104K500JT", "", "", "100nF", "", "{}"),
                (4, "CAP-27-ALT", "C777004", "Capacitors - MLCC", "0603", "M11", "CAP-27-ALT", "", "", "27pF", "", "{}"),
            ],
        )
    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", jlc_path)
    monkeypatch.setattr(dynamic, "JLCPARTS_DB_PATH", jlc_path)
    monkeypatch.setattr(libraries, "ALTIUM_DB_PATH", altium_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def row(**overrides):
    result = {
        "supplier_part": "", "quantity": 1, "designator": "C1",
        "footprint": "C0603_Slim", "comment": "27pF", "value": "27pF",
        "manufacturer_part": "", "manufacturer": "",
        "primary_category": "Capacitors", "secondary_category": "",
        "pin_count": "2",
    }
    result.update(overrides)
    return result


def test_parser_keeps_value_category_and_pin_count():
    content = "Quantity,Comment,Value,Primary Category,Secondary Category,Pin Count\n1,220pF,220pF,Capacitors,MLCC,2\n"
    parsed = parse_bom_file(content.encode(), "bom.csv")
    assert parsed[0]["value"] == "220pF"
    assert parsed[0]["primary_category"] == "Capacitors"
    assert parsed[0]["secondary_category"] == "MLCC"
    assert parsed[0]["pin_count"] == "2"


def test_numeric_altium_code_and_equivalent_capacitance_auto_match(matching_databases):
    item = analyze_bom_matching([row(supplier_part="C777001", comment="10uF", value="10uF")], matching_databases)["items"][0]
    assert (item["status"], item["library_source"], item["external_part_id"]) == ("matched_library", "altium", "1")
    assert item["selected"] is True


def test_exact_code_with_wrong_package_requires_review(matching_databases):
    item = analyze_bom_matching([row(supplier_part="C777002", comment="220pF", value="220pF")], matching_databases)["items"][0]
    assert item["status"] == "unmatched"
    assert item["selected"] is False
    assert "package" in item["conflicts"]
    assert item["suggestions"][0]["external_part_id"] == "2"


def test_same_model_wrong_value_is_only_a_suggestion(matching_databases):
    item = analyze_bom_matching([row(supplier_part="", comment="220pF", value="220pF", manufacturer_part="CGA0603X7R104K500JT")], matching_databases)["items"][0]
    assert item["status"] == "unmatched"
    assert item["selected"] is False
    assert all(candidate["external_part_id"] != "3" for candidate in item["suggestions"])
    assert item["suggestions"][0]["library_source"] == "jlcparts"
    assert item["suggestions"][0]["external_part_id"] == "100004"
    assert "value" in item["conflicts"]


@pytest.mark.parametrize("text,expected", [("5.1kΩ", "5100"), ("5.1k", "5100"),
                                         ("5K1", "5100"), ("0R", "0"), ("1R0", "1")])
def test_resistor_notations_are_equivalent(text, expected):
    assert measurement(text, "resistor") == int(expected)


def test_ic_package_mismatch_is_detected_without_passive_value():
    bom = row(designator="U1", footprint="ESOP-8_L4.9-W3.9-P1.27-LS6.0-BL-EP",
              comment="TP4056", value="TP4056", primary_category="Integrated Circuits")
    candidate = {"category": "Integrated Circuits", "package": "SOT-23-6"}
    assert candidate_conflicts(bom, candidate, None) == ["package"]


def test_comment_value_is_used_when_value_column_is_not_numeric(matching_databases):
    item = analyze_bom_matching([row(supplier_part="", value="Ceramic capacitor", comment="27pF")], matching_databases)["items"][0]
    assert item["suggestions"][0]["external_part_id"] == "100002"


def test_inventory_reference_survives_missing_external_record(matching_databases):
    part = Part(library_source="jlcparts", external_part_id="999998")
    matching_databases.add(part)
    matching_databases.flush()
    matching_databases.add(Inventory(part_id=part.id, quantity_available=12))
    matching_databases.flush()
    item = analyze_bom_matching([row(supplier_part="C999998")], matching_databases)["items"][0]
    assert item["status"] == "unmatched"
    assert item["suggestions"][0]["external_part_id"] == "999998"
    assert item["suggestions"][0]["stock"] == 12


def test_passive_substitutes_put_jlc_first_and_include_zero_stock(matching_databases):
    item = analyze_bom_matching([row(supplier_part="C999999", manufacturer_part="CAP-27-ALT")], matching_databases)["items"][0]
    assert item["status"] == "unmatched"
    assert item["selected"] is False
    assert [candidate["external_part_id"] for candidate in item["suggestions"][:2]] == ["100002", "100001"]
    assert any(candidate["external_part_id"] == "4" for candidate in item["suggestions"])
    assert all(candidate["external_part_id"] != "100003" for candidate in item["suggestions"])
    assert item["suggestions"][0]["voltage"] == "25V"
    assert item["suggestions"][0]["tolerance"] == "±10%"


def test_inductor_and_crystal_dimensions_find_candidates(matching_databases):
    rows = [
        row(designator="L1", supplier_part="", comment="1.5uH", value="1.5uH", footprint="IND-SMD_L2.5-W2.0_MEKK2520TR47M", primary_category="Inductors"),
        row(designator="Y1", supplier_part="", comment="24MHz", value="24MHz", footprint="CRYSTAL-SMD_4P-L3.2-W2.5-BL", primary_category="Crystals", pin_count="4"),
    ]
    items = analyze_bom_matching(rows, matching_databases)["items"]
    assert items[0]["suggestions"][0]["external_part_id"] == "100005"
    assert items[1]["suggestions"][0]["external_part_id"] == "100006"
    assert items[0]["status"] == items[1]["status"] == "unmatched"


def test_led_color_disagreement_requires_review(matching_databases):
    item = analyze_bom_matching([row(designator="LED2", comment="绿", value="绿", footprint="LED0603-RD_ORANGE", primary_category="Optoelectronics")], matching_databases)["items"][0]
    assert "color" in item["conflicts"]
    assert item["suggestions"][0]["external_part_id"] == "100007"
    assert item["selected"] is False


def test_led_cannot_auto_bind_to_capacitor_by_supplier_code(matching_databases):
    item = analyze_bom_matching([row(supplier_part="C100007")], matching_databases)["items"][0]
    assert item["status"] == "unmatched"
    assert "type" in item["conflicts"]


def test_ic_cannot_auto_bind_to_led_by_supplier_code(matching_databases):
    item = analyze_bom_matching([row(designator="U1", primary_category="Integrated Circuits",
                                     comment="LED controller", value="LED controller",
                                     footprint="0603", supplier_part="C100007")], matching_databases)["items"][0]
    assert item["status"] == "unmatched"
    assert "type" in item["conflicts"]


def test_led_designator_with_plain_package_finds_color_candidate(matching_databases):
    item = analyze_bom_matching([row(designator="D1", supplier_part="", comment="绿", value="绿",
                                     footprint="0603", primary_category="Optoelectronics",
                                     secondary_category="LED Indication")], matching_databases)["items"][0]
    assert item["suggestions"][0]["external_part_id"] == "100007"


def test_unconfirmed_substitute_is_rejected_before_project_creation(matching_databases):
    item = analyze_bom_matching([row(supplier_part="C999999")], matching_databases)["items"][0]
    candidate = item["suggestions"][0]
    item.update(status="matched_library", library_source=candidate["library_source"],
                external_part_id=candidate["external_part_id"], selected=True)
    with pytest.raises(ValueError, match="confirmation"):
        execute_bom_import(matching_databases, "new", "TEST_UNCONFIRMED", None, None,
                           "overwrite", [item])
    assert matching_databases.query(Project).count() == 0


def test_unconfirmed_kicad_manual_selection_is_rejected(matching_databases):
    item = row(row_index=1, selected=True, library_source="kicad", external_part_id="12",
               status="matched_library", confirmed_match=False)
    with pytest.raises(ValueError, match="confirmation"):
        execute_bom_import(matching_databases, "new", "TEST_KICAD_UNCONFIRMED", None, None,
                           "overwrite", [item])
    assert matching_databases.query(Project).count() == 0


def test_confirmed_substitute_imports(matching_databases):
    item = analyze_bom_matching([row(supplier_part="C999999")], matching_databases)["items"][0]
    candidate = item["suggestions"][0]
    item.update(status="matched_library", library_source=candidate["library_source"],
                external_part_id=candidate["external_part_id"], selected=True,
                confirmed_match=True)
    result = execute_bom_import(matching_databases, "new", "TEST_CONFIRMED", None, None,
                                "overwrite", [item])
    assert result["imported_parts_count"] == 1
    assert result["skipped_unresolved_count"] == 0


@pytest.mark.parametrize("code_field", ["manufacturer_part", "comment"])
def test_fallback_supplier_code_auto_match_imports_without_extra_confirmation(matching_databases, code_field):
    bom = row(supplier_part="", value="27pF", comment="27pF", manufacturer_part="")
    bom[code_field] = "C100002"
    item = analyze_bom_matching([bom], matching_databases)["items"][0]
    assert item["match_reason"] == "exact_supplier_code"
    assert item["confirmed_match"] is False
    result = execute_bom_import(matching_databases, "new", "TEST_FALLBACK_CODE", None, None,
                                "overwrite", [item])
    assert result["imported_parts_count"] == 1


def test_import_schema_keeps_matching_context():
    item = BomImportItem(row_index=1, raw_supplier_part="C777001", value="10uF",
                         primary_category="Capacitors", pin_count="2", confirmed_match=True)
    serialized = item.model_dump()
    assert serialized["raw_supplier_part"] == "C777001"
    assert serialized["value"] == "10uF"
    assert serialized["primary_category"] == "Capacitors"
    assert serialized["pin_count"] == "2"
    assert serialized["confirmed_match"] is True


def test_bom_manual_search_keeps_package_and_reports_conflicts(matching_databases):
    response = TestClient(app).post("/api/projects/bom/suggest", json={
        "item": row(row_index=1, comment="220pF", value="220pF"), "query": "220pF",
    })
    assert response.status_code == 200
    assert response.json()["items"][0]["external_part_id"] == "100004"
    response = TestClient(app).post("/api/projects/bom/suggest", json={
        "item": row(row_index=1, comment="220pF", value="220pF"), "query": "C777002",
    })
    assert response.status_code == 200
    assert response.json()["items"][0]["conflicts"] == ["package"]


def test_missing_supplier_code_search_falls_back_to_value_and_package(matching_databases):
    response = TestClient(app).post("/api/projects/bom/suggest", json={
        "item": row(row_index=1, raw_supplier_part="C999999"), "query": "C999999",
    })
    assert response.status_code == 200
    assert response.json()["items"][0]["external_part_id"] == "100002"


def test_preview_does_not_write_main_database(matching_databases):
    before = matching_databases.connection().exec_driver_sql("SELECT total_changes()").scalar_one()
    analyze_bom_matching([row(supplier_part="C777001", value="10uF", comment="10uF")], matching_databases)
    after = matching_databases.connection().exec_driver_sql("SELECT total_changes()").scalar_one()
    assert after == before


def remote_capacitor_product(code, package="0603", capacitance="27pF"):
    return {
        "productCode": f"C{code}",
        "productModel": f"REMOTE-CAP-{code}",
        "parentCatalogName": "Capacitors",
        "catalogName": "MLCC",
        "brandNameEn": "Remote Manufacturer",
        "encapStandard": package,
        "stockNumber": 321,
        "isRohsCert": True,
        "productDescEn": f"{capacitance} ceramic capacitor",
        "pdfUrl": "https://example.test/capacitor.pdf",
        "productPriceList": [{"ladder": 1, "usdPrice": 0.02}],
        "paramVOList": [{"paramNameEn": "Capacitance", "paramValueEn": capacitance}],
    }


def remote_crystal_product(code, package="SMD3225-4P", frequency="24MHz"):
    return {
        "productCode": f"C{code}",
        "productModel": f"REMOTE-XTAL-{code}",
        "parentCatalogName": "Crystals, Oscillators, Resonators",
        "catalogName": "Crystals",
        "brandNameEn": "Remote Manufacturer",
        "encapStandard": package,
        "stockNumber": 85,
        "isRohsCert": True,
        "productDescEn": f"{frequency} crystal",
        "pdfUrl": "https://example.test/crystal.pdf",
        "productPriceList": [{"ladder": 1, "usdPrice": 0.04}],
        "paramVOList": [{"paramNameEn": "Frequency", "paramValueEn": frequency}],
    }


def test_bom_preview_dynamically_matches_missing_exact_c_code(matching_databases, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: calls.append(code) or remote_capacitor_product(code),
    )

    item = analyze_bom_matching(
        [row(supplier_part="C999999")], matching_databases
    )["items"][0]

    assert item["status"] == "matched_library"
    assert item["library_source"] == "jlcparts"
    assert item["external_part_id"] == "999999"
    assert item["matched_part_name"] == "REMOTE-CAP-999999"
    assert item["selected"] is True
    assert calls == [999999]


def test_supplied_workbook_dynamic_crystal_regression(matching_databases, monkeypatch):
    workbook = (
        Path(__file__).resolve().parents[2]
        / "BOM"
        / "BOM__v0.6_0603_PCB1_3_2026-09-29.xlsx"
    )
    if not workbook.exists():
        pytest.skip("Supplied BOM workbook is not available beside the repository")

    parsed_rows = parse_bom_file(workbook.read_bytes(), workbook.name)
    crystal_row = next(row for row in parsed_rows if row.get("supplier_part") == "C70590")
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: remote_crystal_product(code),
    )
    before = {
        "parts": matching_databases.query(Part).count(),
        "inventory": matching_databases.query(Inventory).count(),
        "projects": matching_databases.query(Project).count(),
    }

    matched = analyze_bom_matching([crystal_row], matching_databases)["items"][0]
    conflicting_row = dict(crystal_row, footprint="CRYSTAL-SMD_4P-L2.5-W2.0")
    conflict = analyze_bom_matching([conflicting_row], matching_databases)["items"][0]

    assert matched["status"] == "matched_library"
    assert matched["external_part_id"] == "70590"
    assert matched["matched_part_name"] == "REMOTE-XTAL-70590"
    assert conflict["status"] == "unmatched"
    assert conflict["selected"] is False
    assert "package" in conflict["suggestions"][0]["conflicts"]
    assert before == {
        "parts": matching_databases.query(Part).count(),
        "inventory": matching_databases.query(Inventory).count(),
        "projects": matching_databases.query(Project).count(),
    }


def test_unmatched_bom_refreshes_and_overwrites_conflicting_local_code(
    matching_databases, monkeypatch
):
    conn = sqlite3.connect(libraries.JLCPARTS_DB_PATH)
    try:
        conn.execute(
            """
            UPDATE jlc_components SET fetched_at = 1, present = 0, sync_seen = 1,
                category = 'Old Category', subcategory = 'Old Subcategory',
                mfr = 'CAP-220', package = '0402', manufacturer = 'Old Manufacturer',
                library_type = 'expand', preferred = 1, last_on_stock = 2,
                description = 'Old description', datasheet = 'old.pdf', stock = 0,
                price = 'old-price', attributes = '{"Old":"value"}', rohs = 0,
                eccn = 'OLD', assembly = 1, assembly_process = 'old-process',
                assembly_mode = 'old-mode', website_component_id = 'old-id',
                attrition = '{"Old":1}' WHERE lcsc = 100004
            """
        )
        conn.execute(
            """
            INSERT INTO lcsc_components
                (lcsc, fetched_at, manufacturer, attributes, image, url_slug)
            VALUES (100004, 1, 'Old Manufacturer', '{"Old":"value"}', 'old.png', 'old')
            """
        )
        conn.commit()
    finally:
        conn.close()

    calls = []
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: calls.append(code) or remote_capacitor_product(code),
    )

    item = analyze_bom_matching(
        [row(supplier_part="C100004", value="27pF", comment="27pF")],
        matching_databases,
    )["items"][0]

    assert item["status"] == "matched_library"
    assert item["external_part_id"] == "100004"
    assert item["selected"] is True
    assert calls == [100004]
    stored = libraries.get_connection(libraries.JLCPARTS_DB_PATH)
    try:
        updated = stored.execute(
            """
            SELECT fetched_at, present, sync_seen, category, subcategory, mfr,
                   package, manufacturer, library_type, preferred, description,
                   datasheet, stock, price, attributes, rohs, eccn, assembly,
                   assembly_process, assembly_mode, website_component_id, attrition
            FROM jlc_components WHERE lcsc = 100004
            """
        ).fetchone()
        metadata = stored.execute(
            "SELECT manufacturer, attributes, image, url_slug FROM lcsc_components WHERE lcsc = 100004"
        ).fetchone()
    finally:
        stored.close()
    assert updated[0] > 1
    assert tuple(updated[1:14]) == (
        1, 0, "Capacitors", "MLCC", "REMOTE-CAP-100004", "0603",
        "Remote Manufacturer", "lcsc_dynamic", 0,
        "27pF ceramic capacitor", "https://example.test/capacitor.pdf",
        321, "1-:0.02",
    )
    assert json.loads(updated[14]) == {"Capacitance": "27pF"}
    assert updated[15:18] == (1, "-", None)
    assert updated[18:] == (None, None, None, "{}")
    assert metadata[0] == "Remote Manufacturer"
    assert json.loads(metadata[1]) == {"Capacitance": "27pF"}
    assert metadata[2:] == (None, None)


def test_bom_preview_deduplicates_dynamic_queries_for_repeated_c_codes(
    matching_databases, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: calls.append(code) or remote_capacitor_product(code),
    )

    items = analyze_bom_matching(
        [row(supplier_part="C999999", designator="C1"),
         row(supplier_part="C999999", designator="C2")],
        matching_databases,
    )["items"]

    assert [item["status"] for item in items] == ["matched_library", "matched_library"]
    assert calls == [999999]


def test_bom_without_lcsc_code_does_not_run_dynamic_lookup(matching_databases, monkeypatch):
    def unexpected_fetch(code):
        pytest.fail(f"BOM row without an LCSC code must not query C{code}")

    monkeypatch.setattr(dynamic, "fetch_lcsc_product", unexpected_fetch)
    item = analyze_bom_matching(
        [row(supplier_part="", manufacturer_part="REMOTE-MPN", comment="27pF")],
        matching_databases,
    )["items"][0]

    assert item["status"] == "unmatched"


def test_dynamic_c_code_with_package_conflict_requires_review(matching_databases, monkeypatch):
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: remote_capacitor_product(code, package="0402"),
    )

    item = analyze_bom_matching(
        [row(supplier_part="C999998")], matching_databases
    )["items"][0]

    assert item["status"] == "unmatched"
    assert item["selected"] is False
    assert item["suggestions"][0]["external_part_id"] == "999998"
    assert "package" in item["suggestions"][0]["conflicts"]


def test_dynamic_refresh_failure_keeps_existing_catalog_record(matching_databases, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dynamic, "fetch_lcsc_product", lambda code: calls.append(code) or None
    )

    item = analyze_bom_matching(
        [row(supplier_part="C100004", value="27pF", comment="27pF")],
        matching_databases,
    )["items"][0]

    assert item["status"] == "unmatched"
    assert item["selected"] is False
    assert calls == [100004]
    conn = sqlite3.connect(libraries.JLCPARTS_DB_PATH)
    try:
        mfr = conn.execute(
            "SELECT mfr FROM jlc_components WHERE lcsc = 100004"
        ).fetchone()[0]
    finally:
        conn.close()
    assert mfr == "CAP-220"


def test_bom_preview_limits_remote_requests_to_four_concurrent_codes(
    matching_databases, monkeypatch
):
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def fetch(code):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(0.05)
            return remote_capacitor_product(code)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(dynamic, "fetch_lcsc_product", fetch)
    rows = [row(supplier_part=f"C{900000 + index}", designator=f"C{index}")
            for index in range(1, 7)]

    items = analyze_bom_matching(rows, matching_databases)["items"]

    assert all(item["status"] == "matched_library" for item in items)
    assert state["peak"] == 4


def test_bom_manual_search_and_library_search_share_dynamic_code_result(
    matching_databases, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: calls.append(code) or remote_capacitor_product(code),
    )
    client = TestClient(app)

    manual = client.post("/api/projects/bom/suggest", json={
        "item": row(row_index=1, value="27pF", comment="27pF"),
        "query": "C999997",
    })
    preview = analyze_bom_matching(
        [row(supplier_part="C999997")], matching_databases
    )["items"][0]
    library = client.get("/api/libraries/jlcparts?q=C999997")
    global_search = client.get(
        "/api/search/aggregate?q=C999997&tab=jlcparts&page=1&page_size=5"
    )

    assert manual.status_code == 200
    assert manual.json()["items"][0]["external_part_id"] == "999997"
    assert preview["status"] == "matched_library"
    assert library.status_code == 200
    assert library.json()["items"][0]["source"] == "lcsc_dynamic"
    assert global_search.status_code == 200
    assert global_search.json()["items"][0]["source"] == "lcsc_dynamic"
    assert calls == [999997]


def test_supplied_workbook_regression():
    if os.getenv("PARTSHELF_TEST_LOCAL_BOM") != "1":
        pytest.skip("Local BOM regression requires PARTSHELF_TEST_LOCAL_BOM=1")
    path = Path(r"E:\workspace\RadioLabRepoBackend\BOM\BOM__v0.6_0603_PCB1_3_2026-09-29.xlsx")
    if not path.is_file() or not libraries.JLCPARTS_DB_PATH.is_file() or not libraries.ALTIUM_DB_PATH.is_file():
        pytest.skip("Local BOM workbook or external libraries are unavailable")
    rows = parse_bom_file(path.read_bytes(), path.name)
    with SessionLocal() as db:
        items = analyze_bom_matching(rows, db)["items"]
    assert len(items) == 40
    exact_altium = [item for item in items if item["library_source"] == "altium" and item["match_reason"] == "exact_supplier_code"]
    exact_altium += [item for item in items if any(candidate["library_source"] == "altium" and candidate["match_reason"] == "exact_supplier_code" for candidate in item["suggestions"])]
    assert len(exact_altium) == 16
    assert "package" in items[1]["conflicts"]
    assert "value" in items[5]["conflicts"]
    assert items[13]["suggestions"][0]["value"] == "1.5uH"
    assert items[39]["suggestions"][0]["value"] == "24MHz"
