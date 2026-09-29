import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.services import external_library_service as libraries
from app.services.inventory_service import InventoryService
from app.services import search_alias_service
from app.services.search_alias_service import (
    SearchAliasRegistry,
    aliases_for_record,
    expand_query,
    record_keys,
)
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


@pytest.fixture
def search_libraries(tmp_path, monkeypatch):
    jlc_path = tmp_path / "jlcparts.db"
    conn = sqlite3.connect(jlc_path)
    conn.executescript(
        """
        CREATE TABLE jlc_components (
            lcsc INTEGER PRIMARY KEY, category TEXT, subcategory TEXT,
            mfr TEXT, package TEXT, joints INTEGER, manufacturer TEXT,
            library_type TEXT, preferred INTEGER, stock INTEGER, price TEXT,
            description TEXT, datasheet TEXT, attributes TEXT, rohs INTEGER
        );
        CREATE TABLE lcsc_components (
            lcsc INTEGER PRIMARY KEY, image TEXT, url_slug TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO jlc_components
        (lcsc, category, subcategory, mfr, package, joints, manufacturer,
         library_type, preferred, stock, price, description, datasheet,
         attributes, rohs)
        VALUES (?, 'Passive', '', ?, '0603', 2, 'Fixture', 'base', 0,
                ?, '', ?, '', ?, 1)
        """,
        [
            (201, "CAP-RAW", 1, "电容器 1uF", json.dumps({"Capacitance": "1uF"})),
            (202, "CAP-ALIAS", 100, "Capacitor 1uF", json.dumps({"Capacitance": "1uF"})),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", jlc_path)

    altium_path = tmp_path / "altium.db"
    conn = sqlite3.connect(altium_path)
    conn.execute(
        """
        CREATE TABLE altium_components (
            id INTEGER PRIMARY KEY, lib_reference TEXT, lcsc_part TEXT,
            category TEXT, package TEXT, manufacturer TEXT,
            mfr_part_number TEXT, basic_part INTEGER, description TEXT,
            resistance TEXT, capacitance TEXT, inductance TEXT, tolerance TEXT,
            voltage_rating TEXT, power_rating TEXT, datasheet_url TEXT,
            jlcpcb_url TEXT, lcsc_url TEXT, parameters_json TEXT, source_file TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO altium_components
        (id, lib_reference, lcsc_part, category, package, manufacturer,
         mfr_part_number, basic_part, description, resistance, capacitance,
         inductance, tolerance, voltage_rating, power_rating, datasheet_url,
         jlcpcb_url, lcsc_url, parameters_json, source_file)
        VALUES (?, ?, '', 'Passive', '0603', 'Fixture', '', 1, ?, '', '', '',
                '', '', '', '', '', '', ?, 'fixture.schlib')
        """,
        [
            (1, "AliasCap", "Ceramic part", json.dumps({"Function": "Capacitor"})),
            (2, "RawCap", "电容器陶瓷", json.dumps({"Function": "Passive"})),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(libraries, "ALTIUM_DB_PATH", altium_path)

    kicad_path = tmp_path / "kicad.db"
    conn = sqlite3.connect(kicad_path)
    conn.execute(
        """
        CREATE TABLE kicad_symbols (
            id INTEGER PRIMARY KEY, library TEXT, name TEXT, extends TEXT,
            reference TEXT, value TEXT, footprint TEXT, datasheet TEXT,
            description TEXT, keywords TEXT, fp_filters TEXT, in_bom INTEGER,
            on_board INTEGER, properties_json TEXT, source_file TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO kicad_symbols
        (id, library, name, extends, reference, value, footprint, datasheet,
         description, keywords, fp_filters, in_bom, on_board,
         properties_json, source_file)
        VALUES (?, ?, ?, '', 'C', ?, '', '', ?, ?, '', 1, 1, '{}', 'fixture')
        """,
        [
            (1, "A-Alias", "Capacitor", "Capacitor", "Ceramic", "capacitor"),
            (2, "Z-Raw", "电容器", "电容器", "陶瓷", ""),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(libraries, "KICAD_DB_PATH", kicad_path)


def test_jlcparts_search_expands_common_alias_but_keeps_original_matches_first(search_libraries):
    result = libraries.search_jlcparts("电容", page_size=10)

    assert [item["lcsc"] for item in result["items"]] == [201, 202]
    assert result["total"] == 2


def test_jlcparts_original_metadata_match_stays_ahead_across_pages(search_libraries):
    first_page = libraries.search_jlcparts("电容", page=1, page_size=1)
    second_page = libraries.search_jlcparts("电容", page=2, page_size=1)

    assert [item["lcsc"] for item in first_page["items"]] == [201]
    assert [item["lcsc"] for item in second_page["items"]] == [202]
    assert first_page["total"] == second_page["total"] == 2


def test_fullwidth_query_keeps_its_normalized_native_match(search_libraries):
    query = "ＣＡＰＡＣＩＴＯＲ"
    jlc = libraries.search_jlcparts(query, page_size=10)
    altium = libraries.search_altium(query, page_size=10)
    kicad = libraries.search_kicad(query, page_size=10)

    assert [item["lcsc"] for item in jlc["items"]] == [202, 201]
    assert [item["id"] for item in altium["items"]] == [1, 2]
    assert [item["id"] for item in kicad["items"]] == [1, 2]


def test_altium_search_expands_alias_in_structured_parameters_after_original(search_libraries):
    result = libraries.search_altium("电容", page_size=10)

    assert [item["id"] for item in result["items"]] == [2, 1]
    assert result["total"] == 2


def test_kicad_search_expands_alias_in_keywords_after_original(search_libraries):
    result = libraries.search_kicad("电容", page_size=10)

    assert [item["id"] for item in result["items"]] == [2, 1]
    assert result["total"] == 2


def test_kicad_record_aliases_preserve_requested_library_filter(search_libraries, monkeypatch):
    registry = SearchAliasRegistry({
        "synonym_groups": [],
        "record_aliases": {
            "kicad": {
                "A-Alias|Capacitor": ["Legacy A"],
                "Z-Raw|电容器": ["Legacy Z"],
            },
        },
    })
    monkeypatch.setattr(search_alias_service, "search_aliases", registry)

    query = "Legacy A Legacy Z"
    unfiltered = libraries.search_kicad(query, page_size=10)
    filtered = libraries.search_kicad(query, library="A-Alias", page_size=10)

    assert [item["id"] for item in unfiltered["items"]] == [1, 2]
    assert [item["id"] for item in filtered["items"]] == [1]


def test_altium_package_and_kicad_library_are_actual_search_fields(search_libraries):
    altium = libraries.search_altium("0603", page_size=10)
    kicad = libraries.search_kicad("Z-Raw", page_size=10)

    assert [item["id"] for item in altium["items"]] == [1, 2]
    assert [item["id"] for item in kicad["items"]] == [2]


def test_inventory_search_expands_alias_without_displacing_original_matches(monkeypatch):
    rows = [
        SimpleNamespace(
            id=1, library_source="jlcparts", external_part_id="101",
            name="Capacitor 1uF", manufacturer="Fixture", package="0603",
            part_type="Capacitor", storage_location="A1", note="",
        ),
        SimpleNamespace(
            id=2, library_source="jlcparts", external_part_id="102",
            name="电容器 1uF", manufacturer="Fixture", package="0603",
            part_type="电容", storage_location="A2", note="",
        ),
    ]
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: rows)

    results = InventoryService.search("电容", db=None)

    assert [item.id for item in results] == [2, 1]


def test_inventory_curated_alias_does_not_rank_as_native_match(monkeypatch):
    rows = [
        SimpleNamespace(
            id=41, library_source="jlcparts", external_part_id="101",
            name="CAP-RAW", manufacturer="Fixture", package="0603",
            part_type="Passive", storage_location="A1", note="",
        ),
        SimpleNamespace(
            id=42, library_source="custom", external_part_id="",
            name="Inventory Alternate", manufacturer="Fixture", package="0603",
            part_type="Passive", storage_location="A2", note="",
        ),
    ]
    registry = SearchAliasRegistry({
        "synonym_groups": [],
        "record_aliases": {"inventory": {"jlcparts:101": ["Inventory Alternate"]}},
    })
    monkeypatch.setattr(search_alias_service, "search_aliases", registry)
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: rows)

    results = InventoryService.search("Inventory Alternate", db=None)

    assert [item.id for item in results] == [42, 41]


def test_inventory_long_native_note_remains_searchable(monkeypatch):
    note = "UniqueNote " + ("x" * 600)
    row = SimpleNamespace(
        id=51, library_source="custom", external_part_id="", name="Part",
        manufacturer="Fixture", package="0603", part_type="Passive",
        storage_location="A3", note=note,
    )
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: [row])

    results = InventoryService.search("UniqueNote", db=None)

    assert [item.id for item in results] == [51]


def test_fastener_queries_expand_mechanical_synonyms_without_cross_domain_noise():
    assert "nut" in expand_query("螺母", "fasteners")
    assert expand_query("电容", "fasteners") == ("电容",)


def test_query_expansion_normalizes_width_and_caps_one_hop_variants():
    variants = expand_query("ＣＡＰＡＣＩＴＯＲ", "jlcparts")
    limited = SearchAliasRegistry({
        "max_query_variants": 2,
        "synonym_groups": [{"terms": ["part", "component", "item", "device"]}],
    }).expand_query("part", "jlcparts")
    single = SearchAliasRegistry({
        "max_query_variants": 1,
        "synonym_groups": [{"terms": ["part", "component"]}],
    }).expand_query("part", "jlcparts")

    assert "电容" in variants
    assert len(limited) == 2
    assert len({item.casefold() for item in limited}) == 2
    assert single == ("part",)


def test_record_alias_adapter_reads_native_fields_and_stable_keys_for_each_source():
    jlc_aliases = aliases_for_record("jlcparts", {
        "lcsc": 123, "mfr": "CAP123", "attributes": '{"Capacitance":"27pF"}',
    })
    altium_aliases = aliases_for_record("altium", {
        "lib_reference": "CAP27", "parameters_json": '{"Value":"27pF"}',
    })
    kicad_aliases = aliases_for_record("kicad", {
        "library": "Device", "name": "C", "keywords": "capacitor",
        "fp_filters": "C_*", "properties_json": '{"Value":"27pF"}',
    })
    fastener_aliases = aliases_for_record("fasteners", {
        "standard_code": "IUTHeatInsert", "standard_name": "Heat Insert",
    })
    inventory_aliases = aliases_for_record("inventory", {
        "id": 7, "library_source": "jlcparts", "external_part_id": "123",
        "name": "CAP123", "external_details": {"description": "27pF capacitor"},
    })

    assert "27pF" in jlc_aliases
    assert "27pF" in altium_aliases
    assert "capacitor" in kicad_aliases
    assert "热熔螺母" in fastener_aliases
    assert "27pF capacitor" in inventory_aliases
    assert record_keys("jlcparts", {"lcsc": "C123"}) == ("123",)
    assert record_keys("altium", {"source_file": "x.schlib", "lib_reference": "U1"}) == ("x.schlib|U1",)
    assert record_keys("kicad", {"library": "Device", "name": "C"}) == ("Device|C",)
    assert record_keys("fasteners", {"standard_code": "ISO4762"}) == ("ISO4762",)
    assert record_keys("inventory", {"id": 7, "library_source": "jlcparts", "external_part_id": "123"}) == (
        "jlcparts:123", "part:7"
    )


def test_record_aliases_resolve_stable_keys_for_all_five_sources(search_libraries, monkeypatch):
    registry = SearchAliasRegistry({
        "synonym_groups": [],
        "record_aliases": {
            "inventory": {"jlcparts:101": ["Inventory Alternate"]},
            "jlcparts": {"201": ["Legacy Capacitor", "123", "C124"]},
            "altium": {"fixture.schlib|AliasCap": ["Old Cap Reference"]},
            "kicad": {"A-Alias|Capacitor": ["Alternate Symbol Name"]},
            "fasteners": {"IUTHeatInsert": ["Insert Alternate Name"]},
        },
    })
    monkeypatch.setattr(search_alias_service, "search_aliases", registry)
    inventory = [
        SimpleNamespace(
            id=41, library_source="jlcparts", external_part_id="101",
            name="CAP-RAW", manufacturer="Fixture", package="0603",
            part_type="Passive", storage_location="A1", note="",
        )
    ]
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: inventory)

    jlc = libraries.search_jlcparts("Legacy Capacitor", page_size=10)
    altium = libraries.search_altium("Old Cap Reference", page_size=10)
    kicad = libraries.search_kicad("Alternate Symbol Name", page_size=10)
    stock = InventoryService.search("Inventory Alternate", db=None)
    fasteners = libraries.query_fasteners(query="Insert Alternate Name", page_size=20, domain="fasteners")

    assert [item["lcsc"] for item in jlc["items"]] == [201]
    assert [item["lcsc"] for item in libraries.search_jlcparts("123", page_size=10)["items"]] == [201]
    assert [item["lcsc"] for item in libraries.search_jlcparts("C124", page_size=10)["items"]] == [201]
    assert [item["id"] for item in altium["items"]] == [1]
    assert [item["id"] for item in kicad["items"]] == [1]
    assert [item.id for item in stock] == [41]
    assert [item["standard_code"] for item in fasteners["items"]] == ["IUTHeatInsert"]


def test_unified_search_routes_use_alias_expansion_without_changing_response_shape(search_libraries, monkeypatch):
    monkeypatch.setattr(InventoryService, "get_parts_inventory_list", lambda *args, **kwargs: [])

    library_response = client.get("/api/libraries/search?q=电容&target=all&limit=10")
    quick_response = client.get("/api/search/quick?q=电容")
    aggregate_response = client.get("/api/search/aggregate?q=电容&tab=jlcparts&page_size=10")

    assert library_response.status_code == quick_response.status_code == aggregate_response.status_code == 200
    library_data = library_response.json()
    quick_data = quick_response.json()
    aggregate_data = aggregate_response.json()
    assert {"jlcparts", "altium", "kicad", "fasteners"}.issubset(library_data)
    assert {"inventory", "jlcparts", "altium", "kicad", "fasteners"}.issubset(quick_data)
    assert [item["lcsc"] for item in library_data["jlcparts"]] == [201, 202]
    assert [item["lcsc"] for item in quick_data["jlcparts"]["items"]] == [201, 202]
    assert aggregate_data["tab"] == "jlcparts"
    assert [item["lcsc"] for item in aggregate_data["items"]] == [201, 202]
