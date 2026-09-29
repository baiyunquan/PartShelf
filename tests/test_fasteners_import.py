import json
import sqlite3

import pytest

from scripts import import_fasteners as importer


def make_fastener_database(path, titles, *, extra_titles=None, baseline_row=True):
    conn = sqlite3.connect(path)
    importer.create_schema(conn)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO fastener_standards "
        "(standard_code, standard_name, authority, domain, category_group, category_group_zh, "
        "description, param_table_name, length_table_name, has_length, source_file) "
        "VALUES ('TEST', 'Test standard', 'ISO', 'fasteners', 'Fasteners', '紧固件', 'test', 'test_def', 'test_length', 1, 'source')"
    )
    cursor.execute(
        "INSERT INTO fastener_table_titles (table_name, titles_json, source_file) VALUES (?, ?, 'source')",
        ("test_def", json.dumps(titles)),
    )
    cursor.execute(
        "INSERT INTO fastener_table_titles (table_name, titles_json, source_file) VALUES (?, ?, 'source')",
        ("test_length", json.dumps(extra_titles or ["Min", "Max"])),
    )
    if baseline_row:
        cursor.execute(
            "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES ('test_def', 'M2', '[2.0]', 'source')"
        )
    conn.commit()
    conn.close()


def add_user_rows(path):
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES (?, ?, ?, 'user')",
        [
            ("test_def", "user:M3:abc", "[3.0]"),
            ("test_length", "user:M3%404.5:def", "[4.5,4.5]"),
        ],
    )
    conn.commit()
    conn.close()


def fake_build_factory(titles, extra_titles=None):
    def fake_build(source_dir, output_db, whole_spec_db):
        make_fastener_database(output_db, titles, extra_titles=extra_titles)
        return {"standards": 1, "rows": 1}
    return fake_build


def test_reimport_preserves_custom_parameter_and_length_rows(tmp_path, monkeypatch):
    output = tmp_path / "fasteners.db"
    make_fastener_database(output, ["D"])
    add_user_rows(output)
    monkeypatch.setattr(importer, "_build_fasteners_database", fake_build_factory(["D"]))

    result = importer.import_fasteners(output_db=output)

    assert result["migrated_user_rows"] == 2
    conn = sqlite3.connect(output)
    rows = conn.execute(
        "SELECT table_name, row_key, data_json, source_file FROM fastener_tables ORDER BY table_name, row_key"
    ).fetchall()
    conn.close()
    assert ("test_def", "M2", "[2.0]", "source") in rows
    assert ("test_def", "user:M3:abc", "[3.0]", "user") in rows
    assert ("test_length", "user:M3%404.5:def", "[4.5,4.5]", "user") in rows


def test_first_import_validates_and_publishes_staged_database(tmp_path, monkeypatch):
    output = tmp_path / "fasteners.db"
    monkeypatch.setattr(importer, "_build_fasteners_database", fake_build_factory(["D"]))

    result = importer.import_fasteners(output_db=output)

    assert output.exists()
    assert result["migrated_user_rows"] == 0
    conn = sqlite3.connect(output)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_failed_reimport_keeps_previous_database_usable(tmp_path, monkeypatch):
    output = tmp_path / "fasteners.db"
    make_fastener_database(output, ["D"])
    add_user_rows(output)
    original_bytes = output.read_bytes()

    def fail_build(source_dir, output_db, whole_spec_db):
        raise RuntimeError("injected import failure")

    monkeypatch.setattr(importer, "_build_fasteners_database", fail_build)
    with pytest.raises(RuntimeError, match="injected"):
        importer.import_fasteners(output_db=output)

    assert output.read_bytes() == original_bytes
    conn = sqlite3.connect(output)
    custom = conn.execute("SELECT count(*) FROM fastener_tables WHERE source_file='user'").fetchone()[0]
    conn.close()
    assert custom == 2


def test_incompatible_upstream_schema_aborts_replacement(tmp_path, monkeypatch):
    output = tmp_path / "fasteners.db"
    make_fastener_database(output, ["D"])
    add_user_rows(output)
    original_bytes = output.read_bytes()
    monkeypatch.setattr(importer, "_build_fasteners_database", fake_build_factory(["Diameter"]))

    with pytest.raises(ValueError, match="schema changed"):
        importer.import_fasteners(output_db=output)

    assert output.read_bytes() == original_bytes
    conn = sqlite3.connect(output)
    custom_count = conn.execute("SELECT count(*) FROM fastener_tables WHERE source_file='user'").fetchone()[0]
    conn.close()
    assert custom_count == 2
