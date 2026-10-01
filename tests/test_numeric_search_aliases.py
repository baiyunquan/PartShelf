"""Unit equivalence, derived indexes, and compound search regressions."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.services import electrical_value_service as values
from app.services import external_library_service as libraries
from app.services.inventory_service import InventoryService
from app.services.numeric_alias_index import ensure_numeric_aliases
from app.services.numeric_alias_query import build_numeric_sql
from app.services import search_alias_service
from fastapi.testclient import TestClient
from app.main import app
from tests.test_search_alias_integration import search_libraries


@pytest.mark.parametrize("text,kind,value", [
    ("2700pf", "capacitance", "0.0000000027"),
    ("2700000pf", "capacitance", "0.0000027"),
    ("2.7 nF", "capacitance", "0.0000000027"),
    ("２．７ μＦ", "capacitance", "0.0000027"),
    ("2.7e3pF", "capacitance", "0.0000000027"),
    (".0027uF", "capacitance", "0.0000000027"),
    ("4k7", "resistance", "4700"),
    ("4R7", "resistance", "4.7"),
    ("4M7", "resistance", "4700000"),
    ("1mΩ", "resistance", "0.001"),
    ("1MΩ", "resistance", "1000000"),
    ("0ohm", "resistance", "0"),
    ("1000µH", "inductance", "0.001"),
])
def test_measurement_normalization(text, kind, value):
    parsed = values.parse_measurements(text)
    assert [(item.kind, item.value) for item in parsed] == [(kind, value)]


@pytest.mark.parametrize("text", [
    "104", "C2700", "BZX55C27PF-M", "SDFL1608Q4R7KTF", "-27pF",
    "2.7-10nF", "2.7nF–10nF", "1e9999F", "1mm", "1Hz",
    "2.7nF~10nF", "2.7~10nF", "2.7nF to 10nF", "2.7至10nF",
    "ABC-4R7-K", "ABC-27PF-M", "ABC-27PF", "27PF-MODEL",
])
def test_ambiguous_input_does_not_create_measurements(text):
    assert values.parse_measurements(text) == ()


@pytest.fixture
def numeric_libraries(search_libraries):
    conn = sqlite3.connect(libraries.JLCPARTS_DB_PATH)
    records = [
        (301, "CAP-EQ", "Capacitors", "0603", 2, "MLCC", {"Capacitance": "2.7nF"}),
        (302, "CAP-TEXT", "Capacitors", "0603", 900, "2700pF textual entry", {}),
        (303, "CAP-LARGER", "Capacitors", "0603", 99, "12700pF", {}),
        (304, "CAP-UF", "Capacitors", "0805", 1, "2.7uF", {}),
        (305, "RES-EQ", "Resistors", "0603", 5, "4.7kΩ", {}),
        (306, "IND-EQ", "Inductors", "0603", 5, "1mH", {}),
        (307, "CAP-FUZZY", "Capacitors", "0603", 999, "227pF", {}),
        (308, "CAP-SMALL", "Capacitors", "0603", 1, "27pF", {}),
    ]
    conn.executemany(
        "INSERT INTO jlc_components (lcsc,mfr,category,package,stock,description,"
        "attributes,preferred,library_type) VALUES (?,?,?,?,?,?,?,0,'base')",
        [(*row[:-1], json.dumps(row[-1])) for row in records],
    )
    conn.commit()
    conn.close()
    for path, sql in [
        (libraries.ALTIUM_DB_PATH,
         "INSERT INTO altium_components (id,lib_reference,category,package,"
         "capacitance,parameters_json,source_file) "
         "VALUES (21,'CAP-EQ','Capacitors','0603','2.7 nF','{}','numeric')"),
        (libraries.KICAD_DB_PATH,
         "INSERT INTO kicad_symbols (id,library,name,value,description,footprint,"
         "properties_json,reference) "
         "VALUES (21,'Numeric','CAP-EQ','2.7nF','capacitor','0603','{}','C')"),
    ]:
        conn = sqlite3.connect(path)
        conn.execute(sql)
        conn.commit()
        conn.close()


def test_equivalence_and_compound_queries_all_catalogs(numeric_libraries):
    for search, identity in [
        (libraries.search_jlcparts, "lcsc"),
        (libraries.search_altium, "id"),
        (libraries.search_kicad, "id"),
    ]:
        result = search("电容 2700pf 0603", page_size=20)
        expected = 301 if identity == "lcsc" else 21
        assert expected in [item[identity] for item in result["items"]], search.__name__
        assert not search("电容 2700pf 1206", page_size=20)["items"]


def test_physical_equivalence_and_fuzzy_results_have_separate_ranks(numeric_libraries):
    result = libraries.search_jlcparts("27pf", page_size=20)
    ids = [item["lcsc"] for item in result["items"]]
    assert ids.index(308) < ids.index(307)
    result = libraries.search_jlcparts("2700000pf", page_size=20)
    assert [item["lcsc"] for item in result["items"]] == [304]
    assert libraries.search_jlcparts("4k7")["items"][0]["lcsc"] == 305
    assert libraries.search_jlcparts("1000uH")["items"][0]["lcsc"] == 306


def test_equivalence_filters_and_pagination(numeric_libraries):
    first = libraries.search_jlcparts("2700pf", page=1, page_size=1, package="0603")
    second = libraries.search_jlcparts("2700pf", page=2, page_size=1, package="0603")
    beyond = libraries.search_jlcparts("2700pf", page=99, page_size=1, package="0603")
    assert first["total"] == second["total"] == beyond["total"] == 3
    assert first["items"][0]["lcsc"] == 302
    assert second["items"][0]["lcsc"] == 301
    assert beyond["items"] == []


def test_index_rebuild_and_changes_are_idempotent(numeric_libraries):
    conn = libraries.get_connection(libraries.JLCPARTS_DB_PATH)
    report = ensure_numeric_aliases(conn, "jlcparts", force=True, batch_size=2)
    before = conn.execute("SELECT * FROM numeric_search_aliases ORDER BY record_id,kind,value").fetchall()
    ensure_numeric_aliases(conn, "jlcparts", force=True, batch_size=3)
    after = conn.execute("SELECT * FROM numeric_search_aliases ORDER BY record_id,kind,value").fetchall()
    assert before == after
    assert report["scanned"] == 10
    assert report["aliases"] > 0
    conn.execute("UPDATE jlc_components SET attributes=? WHERE lcsc=301", ('{"Capacitance":"3.3nF"}',))
    conn.execute("DELETE FROM jlc_components WHERE lcsc=304")
    conn.execute("INSERT INTO jlc_components(lcsc,description,attributes) VALUES(399,'2.7nF','broken json')")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM numeric_search_dirty").fetchone()[0] == 3
    ensure_numeric_aliases(conn, "jlcparts")
    assert conn.execute("SELECT value FROM numeric_search_aliases WHERE record_id=301").fetchone()[0] == "0.0000000033"
    assert not conn.execute("SELECT 1 FROM numeric_search_aliases WHERE record_id=304").fetchall()
    assert conn.execute("SELECT value FROM numeric_search_aliases WHERE record_id=399").fetchone()[0] == "0.0000000027"
    plan = conn.execute("EXPLAIN QUERY PLAN SELECT record_id FROM numeric_search_aliases WHERE kind=? AND value=?",
                        ("capacitance", "0.0000000027")).fetchall()
    assert any("idx_numeric_search_lookup" in row[3] for row in plan)
    conn.close()


def test_inventory_uses_linked_and_custom_measurements(numeric_libraries, monkeypatch):
    rows = [SimpleNamespace(
        id=41, library_source="jlcparts", external_part_id="301", name="CAP-EQ",
        package="0603", part_type="Capacitors", note="", manufacturer="Fixture",
    ), SimpleNamespace(
        id=42, library_source="custom", external_part_id="custom1", name="电容",
        package="0603", part_type="电容", note="2.7nF", manufacturer="Fixture",
    )]
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: rows)
    assert [row.id for row in InventoryService.search("电容 2700pf 0603", db=None)] == [41, 42]
    assert not InventoryService.search("电容 2700pf 1206", db=None)


def test_structured_values_override_descriptions_and_model_fragments():
    record = {"attributes": '{"Capacitance":"2.7nF"}', "description": "27pF 1mH",
              "mfr": "SDFL1608Q4R7KTF"}
    assert values.measurements_for_record("jlcparts", record) == (
        ("capacitance", "0.0000000027"), ("inductance", "0.001"),
    )
    assert values.measurements_for_record("kicad", {"name": "C", "value": "C"}) == ()


def test_ranges_and_model_descriptions_do_not_create_indexed_values():
    assert values.measurements_for_record("jlcparts", {
        "attributes": '{"Capacitance":"2.7nF~10nF"}',
        "description": "Model ABC-4R7-K or ABC-27PF-M",
    }) == ()


def test_inventory_accepts_c_prefixed_references(numeric_libraries, monkeypatch):
    row = SimpleNamespace(id=41, library_source="jlcparts", external_part_id="C301",
                          name="CAP-EQ", note="", package="0603", part_type="Capacitors")
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: [row])
    assert [part.id for part in InventoryService.search("2700pf", db=None)] == [41]


def test_inventory_exact_name_has_priority_over_equivalent_values(monkeypatch):
    rows = [SimpleNamespace(id=41, library_source="custom", external_part_id="x1",
                            name="CAP-EQ", note="2.7nF"),
            SimpleNamespace(id=42, library_source="custom", external_part_id="x2",
                            name="2700pf", note="")]
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: rows)
    assert [part.id for part in InventoryService.search("2700pf", db=None)] == [42, 41]


def test_numeric_aliases_ignore_the_text_variant_limit(numeric_libraries, monkeypatch):
    registry = search_alias_service.SearchAliasRegistry({"max_query_variants": 1})
    monkeypatch.setattr(search_alias_service, "search_aliases", registry)
    result = libraries.search_jlcparts("2700000pF")
    assert [item["lcsc"] for item in result["items"]] == [304]


def test_curated_numeric_aliases_are_rebuilt_when_configuration_changes(numeric_libraries, monkeypatch):
    conn = libraries.get_connection(libraries.JLCPARTS_DB_PATH)
    ensure_numeric_aliases(conn, "jlcparts")
    registry = search_alias_service.SearchAliasRegistry({
        "record_aliases": {"jlcparts": {"301": ["22nF", "Legacy Cap"]}},
    })
    monkeypatch.setattr(search_alias_service, "search_aliases", registry)
    assert ensure_numeric_aliases(conn, "jlcparts")["rebuilt"]
    result = libraries.search_jlcparts("Legacy 22000pF")
    assert [item["lcsc"] for item in result["items"]] == [301]
    conn.close()


def test_equivalent_prefixes_and_dimensions_have_distinct_index_keys(numeric_libraries):
    conn = libraries.get_connection(libraries.JLCPARTS_DB_PATH)
    conn.executemany("INSERT INTO jlc_components(lcsc,description,attributes) VALUES(?,?,'{}')",
                     [(401, "1MΩ"), (402, "1mΩ"), (403, "1mH")])
    conn.commit()
    numeric = build_numeric_sql(conn, "jlcparts", "1000000ohm", ("description",), "lcsc")
    rows = conn.execute(f"SELECT lcsc FROM jlc_components WHERE {numeric.exact}", numeric.params).fetchall()
    assert [row[0] for row in rows] == [401]
    conn.close()


def test_read_only_catalog_keeps_text_search_when_index_is_missing(numeric_libraries, caplog):
    conn = sqlite3.connect(libraries.JLCPARTS_DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    numeric = build_numeric_sql(conn, "jlcparts", "27pF", ("description",), "lcsc")
    assert numeric.exact == "(0)"
    rows = conn.execute(f"SELECT lcsc FROM jlc_components WHERE {numeric.condition}", numeric.params).fetchall()
    assert {row[0] for row in rows} == {307, 308}
    assert "Numeric equivalence search is unavailable" in caplog.text
    conn.close()


def test_cli_reports_missing_catalogs_and_incremental_counts(numeric_libraries, capsys):
    from scripts.rebuild_numeric_aliases import main

    args = ["--library-dir", str(libraries.JLCPARTS_DB_PATH.parent), "--source", "jlcparts"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scanned"] == 10
    assert main(args + ["--incremental"]) == 0
    assert json.loads(capsys.readouterr().out)["scanned"] == 0
    assert main(["--library-dir", str(libraries.JLCPARTS_DB_PATH.parent / "missing")]) == 1
    assert all(json.loads(line)["status"] == "missing" for line in capsys.readouterr().out.splitlines())


def test_global_search_interfaces_use_equivalence(numeric_libraries, monkeypatch):
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: [])
    client = TestClient(app)
    for path in ("/api/libraries/search?q=2700pf&target=all&limit=10",
                 "/api/search/quick?q=2700pf",
                 "/api/search/aggregate?q=2700pf&tab=jlcparts&page_size=10"):
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        items = data["items"] if "items" in data else data["jlcparts"]
        if isinstance(items, dict):
            items = items["items"]
        assert 301 in [item["lcsc"] for item in items]
