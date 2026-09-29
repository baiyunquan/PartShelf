import csv
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.fix_basic_library import convert_database


JLC_COLUMNS = """
    CREATE TABLE jlc_components (
        lcsc INTEGER PRIMARY KEY,
        fetched_at INTEGER,
        present INTEGER,
        sync_seen INTEGER,
        category TEXT,
        subcategory TEXT,
        mfr TEXT,
        package TEXT,
        joints INTEGER,
        manufacturer TEXT,
        library_type TEXT NOT NULL,
        preferred INTEGER NOT NULL,
        last_on_stock INTEGER,
        description TEXT,
        datasheet TEXT,
        stock INTEGER NOT NULL,
        price TEXT,
        attributes TEXT,
        rohs INTEGER,
        eccn TEXT,
        assembly INTEGER,
        assembly_process TEXT,
        assembly_mode TEXT,
        website_component_id INTEGER,
        attrition TEXT
    )
"""

ASSEMBLY_FIELDS = [
    "lcsc",
    "Assembly Type",
    "Assembly Type Batch",
    "Assembly Process",
    "Min Order Qty",
    "Attrition Qty",
    "Special Component Fee",
    "Component Library Type",
]


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _create_databases(tmp_path: Path, component_list_ids=(100, 200, 300, 400, 500)):
    target = tmp_path / "jlcparts.db"
    with sqlite3.connect(target) as connection:
        connection.execute(JLC_COLUMNS)
        connection.execute(
            """CREATE TABLE lcsc_components (
                lcsc INTEGER PRIMARY KEY,
                manufacturer TEXT,
                attributes TEXT,
                url_slug TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO lcsc_components VALUES (400, 'LCSC Maker', '{\"Voltage\":\"5V\"}', 'maker-part-C400')"
        )
        connection.execute(
            """INSERT INTO jlc_components (
                lcsc, fetched_at, present, sync_seen, category, subcategory, mfr, package,
                joints, manufacturer, library_type, preferred, last_on_stock, description,
                datasheet, stock, price, attributes, rohs, eccn, assembly, assembly_process,
                assembly_mode, website_component_id, attrition
            ) VALUES (100, 1, 1, 1, 'Capacitors - MLCC', '', 'EXISTING-100', '0603',
                      2, 'Existing', 'expand', 1, 1, 'Existing description', '', 99,
                      '', '{}', 1, '', 0, '', '', NULL, '{}')"""
        )
        connection.execute(
            """INSERT INTO jlc_components (
                lcsc, fetched_at, present, sync_seen, category, subcategory, mfr, package,
                joints, manufacturer, library_type, preferred, last_on_stock, description,
                datasheet, stock, price, attributes, rohs, eccn, assembly, assembly_process,
                assembly_mode, website_component_id, attrition
            ) VALUES (200, 1, 1, 1, '', '', 'EXISTING-200', '', 0, '', 'base', 0, 1,
                      '', '', 7, '', '{}', NULL, '', 0, '', '', NULL, '{}')"""
        )

    assembly_rows = [
        {
            "lcsc": "100",
            "Assembly Type": "smtWeld",
            "Assembly Type Batch": "smtWeld",
            "Assembly Process": "SMT",
            "Min Order Qty": "20",
            "Attrition Qty": "6",
            "Special Component Fee": "0.0",
            "Component Library Type": "base",
        },
        {
            "lcsc": "200",
            "Assembly Type": "smtWeld",
            "Assembly Type Batch": "smtWeld",
            "Assembly Process": "SMT",
            "Min Order Qty": "20",
            "Attrition Qty": "6",
            "Special Component Fee": "0.0",
            "Component Library Type": "expand",
        },
        {
            "lcsc": "200",
            "Assembly Type": "manualWeld",
            "Assembly Type Batch": "manualWeld",
            "Assembly Process": "THT",
            "Min Order Qty": "5",
            "Attrition Qty": "3",
            "Special Component Fee": "0.0",
            "Component Library Type": "expand",
        },
        {
            "lcsc": "300",
            "Assembly Type": "smtWeld",
            "Assembly Type Batch": "smtWeld",
            "Assembly Process": "SMT",
            "Min Order Qty": "10",
            "Attrition Qty": "2",
            "Special Component Fee": "0.0",
            "Component Library Type": "expand",
        },
        {
            "lcsc": "400",
            "Assembly Type": "smtWeld",
            "Assembly Type Batch": "smtWeld",
            "Assembly Process": "SMT",
            "Min Order Qty": "10",
            "Attrition Qty": "2",
            "Special Component Fee": "0.0",
            "Component Library Type": "expand",
        },
        {
            "lcsc": "500",
            "Assembly Type": "smtWeld",
            "Assembly Type Batch": "smtWeld",
            "Assembly Process": "SMT",
            "Min Order Qty": "10",
            "Attrition Qty": "2",
            "Special Component Fee": "0.0",
            "Component Library Type": "expand",
        },
    ]
    assembly_csv = tmp_path / "assembly-details.csv"
    _write_csv(assembly_csv, ASSEMBLY_FIELDS, assembly_rows)

    component_csv = tmp_path / "ComponentList.csv"
    _write_csv(component_csv, ["lcsc"], [{"lcsc": str(code)} for code in component_list_ids])

    altium_db = tmp_path / "altium.db"
    with sqlite3.connect(altium_db) as connection:
        connection.execute(
            """CREATE TABLE altium_components (
                id INTEGER PRIMARY KEY,
                lcsc_part TEXT,
                lib_reference TEXT,
                category TEXT,
                package TEXT,
                manufacturer TEXT,
                mfr_part_number TEXT,
                description TEXT,
                datasheet_url TEXT,
                parameters_json TEXT,
                basic_part INTEGER
            )"""
        )
        connection.execute(
            """INSERT INTO altium_components VALUES
                (1, 'C300', 'R300', 'Resistors', '0603', 'Example Corp', 'R0603-1K',
                 '1 kOhm resistor', 'https://example.test/r0603.pdf',
                 '{"Resistance":"1kOhm","Tolerance":"1%"}', 1)"""
        )

    return target, assembly_csv, component_csv, altium_db


def test_conversion_imports_missing_preferred_parts_and_keeps_source_variants(tmp_path):
    target, assembly_csv, component_csv, altium_db = _create_databases(tmp_path)

    summary = convert_database(target, assembly_csv, component_csv, altium_db)

    assert summary["source_items"] == 5
    assert summary["base_items"] == 1
    assert summary["preferred_items"] == 4
    assert summary["inserted"] == 3
    assert summary["updated"] == 2
    assert summary["metadata_from_altium"] == 1
    assert summary["metadata_from_lcsc"] == 1
    assert summary["metadata_unavailable"] == 1

    with sqlite3.connect(target) as connection:
        rows = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT lcsc, library_type, preferred, mfr, package, manufacturer, stock, "
                "assembly_process, assembly_mode, attributes, attrition FROM jlc_components"
            )
        }

    assert rows[100][:2] == ("base", 0)
    assert rows[100][2] == "EXISTING-100"
    assert rows[100][5] == 99
    assert rows[200][:2] == ("expand", 1)
    assert rows[200][2] == "EXISTING-200"
    assert rows[200][5] == 7
    assert rows[300][:6] == ("expand", 1, "R0603-1K", "0603", "Example Corp", -1)
    assert rows[300][6:9] == ("SMT", "smtWeld", '{"Resistance":"1kOhm","Tolerance":"1%"}')
    assert rows[400][:5] == ("expand", 1, "", "", "LCSC Maker")
    assert json.loads(rows[400][8]) == {"Voltage": "5V"}
    assert rows[500][:5] == ("expand", 1, "", "", "")
    assert json.loads(rows[500][8]) == {}
    assert "imported_by" not in json.loads(rows[200][9])
    assert json.loads(rows[200][9])["source_rows"] == [
        {
            "assembly_type": "smtWeld",
            "assembly_type_batch": "smtWeld",
            "assembly_process": "SMT",
            "min_order_qty": "20",
            "attrition_qty": "6",
            "special_component_fee": "0.0",
        },
        {
            "assembly_type": "manualWeld",
            "assembly_type_batch": "manualWeld",
            "assembly_process": "THT",
            "min_order_qty": "5",
            "attrition_qty": "3",
            "special_component_fee": "0.0",
        },
    ]
    assert json.loads(rows[300][9])["imported_by"] == "fix_basic_library.py"

    with sqlite3.connect(target) as connection:
        connection.execute("UPDATE jlc_components SET stock=50 WHERE lcsc=300")

    second_run = convert_database(target, assembly_csv, component_csv, altium_db)
    assert second_run["inserted"] == 0
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jlc_components").fetchone()[0] == 5
        assert connection.execute("SELECT stock FROM jlc_components WHERE lcsc=200").fetchone()[0] == 7
        assert connection.execute("SELECT stock FROM jlc_components WHERE lcsc=300").fetchone()[0] == 50


def test_conversion_rejects_mismatched_component_list_without_changes(tmp_path):
    target, assembly_csv, component_csv, altium_db = _create_databases(
        tmp_path, component_list_ids=(100, 200)
    )

    with pytest.raises(ValueError, match="component list does not match"):
        convert_database(target, assembly_csv, component_csv, altium_db)

    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jlc_components").fetchone()[0] == 2
        assert connection.execute(
            "SELECT library_type, preferred FROM jlc_components WHERE lcsc=100"
        ).fetchone() == ("expand", 1)
