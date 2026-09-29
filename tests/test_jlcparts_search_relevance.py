"""Search ranking regressions against a small, real SQLite library."""

import json
import sqlite3

import pytest

from app.services import external_library_service as libraries


@pytest.fixture
def jlc_library(tmp_path, monkeypatch):
    path = tmp_path / "jlcparts.db"
    conn = sqlite3.connect(path)
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
    parts = [
        (101, "CAP-A", "Capacitors", "0402", 0, 0, "MLCC", {"Capacitance": "27pF"}),
        (102, "CAP-B", "Capacitors", "0402", 5, 0, "MLCC", {"Capacitance": "27pF"}),
        (103, "CAP-C", "Capacitors", "0402", 5, 1, "MLCC", {"Capacitance": "27pF"}),
        (104, "MOS-A", "Transistors/Thyristors", "SOT-23", 900, 0, "Input capacitance 227pF", {}),
        (105, "BZX55C27PF-M", "Diodes", "DO-35", 800, 0, "Zener diode", {}),
        (106, "27PF-START", "Diodes", "DO-35", 1, 0, "Zener diode", {}),
        (107, "MOS-B", "Transistors/Thyristors", "SOT-23", 2, 0, "Reverse capacitance 27pF", {}),
        (108, "27pF", "Diodes", "DO-35", 0, 0, "Exact model", {}),
    ]
    conn.executemany(
        """
        INSERT INTO jlc_components
        (lcsc, mfr, category, subcategory, package, joints, manufacturer,
         library_type, preferred, stock, price, description, datasheet,
         attributes, rohs)
        VALUES (?, ?, ?, '', ?, 2, 'Fixture', 'expand', ?, ?, '', ?, '', ?, 1)
        """,
        [
            (lcsc, mfr, category, package, preferred, stock, description, json.dumps(attributes))
            for lcsc, mfr, category, package, stock, preferred, description, attributes in parts
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", path)
    return path


def test_exact_capacitance_precedes_stock_and_text_matches(jlc_library):
    result = libraries.search_jlcparts("27pF", page_size=20)

    assert result["total"] == 8
    assert [item["lcsc"] for item in result["items"]] == [
        108, 103, 102, 101, 106, 105, 104, 107
    ]


def test_spaced_capacitance_finds_attribute_only_parts(jlc_library):
    conn = sqlite3.connect(jlc_library)
    conn.execute(
        "UPDATE jlc_components SET attributes = ? WHERE lcsc = 101",
        (json.dumps({"Capacitance": "27 pF"}),),
    )
    conn.commit()
    conn.close()

    result = libraries.search_jlcparts("27 pF", page_size=10)

    assert result["total"] == 8
    assert [item["lcsc"] for item in result["items"]] == [
        108, 103, 102, 101, 106, 105, 104, 107
    ]


def test_exact_model_and_lcsc_code_win(jlc_library):
    conn = sqlite3.connect(jlc_library)
    conn.execute(
        """
        INSERT INTO jlc_components
        (lcsc, mfr, category, subcategory, package, library_type,
         preferred, stock, description, attributes)
        VALUES (109, 'C104EXTRA', 'Diodes', '', 'DO-35', 'expand',
                0, 1000, '', '{}')
        """
    )
    conn.commit()
    conn.close()

    model = libraries.search_jlcparts("BZX55C27PF-M", page_size=10)
    code = libraries.search_jlcparts("C104", page_size=10)
    numeric_code = libraries.search_jlcparts("104", page_size=10)
    filtered_code = libraries.search_jlcparts("C104", category="Diodes", page_size=10)
    empty_code_page = libraries.search_jlcparts("C104", page=3, page_size=1)

    assert model["items"][0]["lcsc"] == 105
    assert [item["lcsc"] for item in code["items"]] == [104, 109]
    assert [item["lcsc"] for item in numeric_code["items"]] == [104, 109]
    assert [item["lcsc"] for item in filtered_code["items"]] == [109]
    assert empty_code_page["total"] == 2
    assert empty_code_page["items"] == []


def test_filters_and_blank_listing_keep_existing_behavior(jlc_library):
    filtered = libraries.search_jlcparts(
        "27pf", category="Capacitors", package="0402", in_stock_only=True
    )
    blank = libraries.search_jlcparts("", page_size=3)

    assert filtered["total"] == 2
    assert [item["lcsc"] for item in filtered["items"]] == [103, 102]
    assert [item["lcsc"] for item in blank["items"]] == [104, 105, 103]


def test_pagination_and_empty_page_preserve_total(jlc_library):
    first = libraries.search_jlcparts("27pf", page=1, page_size=3)
    second = libraries.search_jlcparts("27pf", page=2, page_size=3)
    beyond = libraries.search_jlcparts("27pf", page=10, page_size=3)

    assert first["total"] == second["total"] == beyond["total"] == 8
    assert first["total_pages"] == second["total_pages"] == beyond["total_pages"] == 3
    assert [item["lcsc"] for item in first["items"]] == [108, 103, 102]
    assert [item["lcsc"] for item in second["items"]] == [101, 106, 105]
    assert beyond["items"] == []
