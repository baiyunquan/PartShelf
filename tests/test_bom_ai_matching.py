import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from app.services import external_library_service as libraries
from app.services.bom_service import analyze_bom_matching, execute_bom_import
from app.services.multi_turn_search_service import MultiTurnSearchService
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.project import Project


@pytest.fixture
def mock_multi_turn_library(tmp_path, monkeypatch):
    """Setup a test SQLite library for MultiTurnSearchService."""
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
                (200001, "CL10B104KB8NNNC", "Capacitors", "MLCC", "0603", "Samsung", 1000, json.dumps({"Capacitance": "100nF", "Voltage Rating": "50V"}), "100nF 50V 0603 MLCC"),
                (200002, "CC0603KRX7R9BB104", "Capacitors", "MLCC", "0603", "Yageo", 500, json.dumps({"Capacitance": "100nF", "Voltage Rating": "50V"}), "100nF 50V 0603 X7R"),
                (200003, "RC0603FR-0710KL", "Resistors", "Chip Resistor", "0603", "Yageo", 2000, json.dumps({"Resistance": "10kΩ"}), "10k 1% 0603 Resistor"),
                (200004, "NE555P", "Logic & Timers", "Timers", "DIP-8", "TI", 300, json.dumps({}), "Precision Timer DIP-8"),
            ],
        )

    with sqlite3.connect(altium_path) as conn:
        conn.executescript("""
            CREATE TABLE altium_components (
                id INTEGER PRIMARY KEY, lib_reference TEXT, lcsc_part TEXT,
                category TEXT, package TEXT, manufacturer TEXT,
                mfr_part_number TEXT, description TEXT, resistance TEXT,
                capacitance TEXT, inductance TEXT, parameters_json TEXT
            );
        """)

    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", jlc_path)
    monkeypatch.setattr(libraries, "ALTIUM_DB_PATH", altium_path)
    from app.services import lcsc_dynamic_service as dynamic
    monkeypatch.setattr(dynamic, "JLCPARTS_DB_PATH", jlc_path)
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda *args: None)
    service = MultiTurnSearchService(strict_mode=False)
    def offline():
        raise RuntimeError("Offline model boundary for deterministic tests")
    monkeypatch.setattr(service, "get_extractor_client", offline)
    monkeypatch.setattr(service, "get_reranker_client", offline)
    monkeypatch.setattr("app.services.bom_service.multi_turn_service", service)
    return service, jlc_path


def test_process_bom_row_direct_code(mock_multi_turn_library):
    service, _ = mock_multi_turn_library
    row = {"supplier_part": "C200001", "value": "100nF", "footprint": "0603"}
    res = service.process_bom_row(row)
    assert res["decision"] == "exact_match"
    assert res["selected_component"]["external_part_id"] in ("200001", "C200001")
    assert "Samsung" in res["selected_component"]["manufacturer"]


def test_process_bom_row_passive_search(mock_multi_turn_library):
    service, _ = mock_multi_turn_library
    row = {"value": "100nF", "footprint": "0603", "designator": "C1"}
    res = service.process_bom_row(row)
    assert res["decision"] in ("exact_match", "ambiguous")
    cands = [res["selected_component"]] if res.get("selected_component") else res.get("candidate_components", [])
    assert len(cands) >= 1
    top = cands[0]
    assert "100nF" in top["description"]
    assert top["package"] == "0603"
    assert res.get("reasoning") is not None


def test_analyze_bom_matching_ai_exact_match(mock_multi_turn_library):
    """Verify analyze_bom_matching invokes AI search matching for row without supplier part."""
    service, _ = mock_multi_turn_library
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    rows = [
        {
            "row_index": 1,
            "designator": "C1",
            "quantity": 10,
            "value": "100nF",
            "footprint": "0603",
            "comment": "100nF",
            "manufacturer_part": "CL10B104KB8NNNC",
            "supplier_part": "",
        }
    ]

    result = analyze_bom_matching(rows, db=mock_db, lang="en")
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["status"] == "matched_library"
    assert item["match_reason"] == "ai_exact_match"
    assert item["matched_part_name"] == "CL10B104KB8NNNC"
    assert item["ai_decision"] == "exact_match"
    assert item["ai_reasoning"] is not None


def test_execute_bom_import_ai_exact_match_allowed(tmp_path, mock_multi_turn_library):
    """Ensure execute_bom_import accepts rows with match_reason == 'ai_exact_match' without requiring manual rebind."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'bom_test.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        project = Project(id=1, name="AI BOM Test Project")
        db.add(project)
        db.commit()

        import_items = [
            {
                "row_index": 1,
                "designator": "C1",
                "quantity": 5,
                "value": "100nF",
                "footprint": "0603",
                "library_source": "jlcparts",
                "external_part_id": "200001",
                "matched_part_name": "CL10B104KB8NNNC",
                "matched_manufacturer": "Samsung",
                "matched_package": "0603",
                "match_reason": "ai_exact_match",
                "conflicts": [],
                "selected": True,
                "auto_create_zero_stock": True,
            }
        ]

        summary = execute_bom_import(
            db=db,
            target_type="existing",
            project_name=None,
            project_description=None,
            existing_project_id=1,
            quantity_strategy="add",
            items=import_items,
        )
        assert summary["imported_parts_count"] == 1
        assert summary["skipped_unresolved_count"] == 0

        part = db.query(Part).first()
        assert part is not None
        assert part.external_part_id == "200001"
        assert part.library_source == "jlcparts"
