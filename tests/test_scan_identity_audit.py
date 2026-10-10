import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_read_only_audit_flags_old_altium_namespace_without_guessing_a_fix(tmp_path):
    main = tmp_path / "main.sqlite"
    with sqlite3.connect(main) as db:
        db.execute("CREATE TABLE parts(id INTEGER PRIMARY KEY,library_source TEXT,external_part_id TEXT)")
        db.execute("CREATE TABLE scan_sessions(id TEXT PRIMARY KEY,status TEXT,part_id INTEGER,component TEXT,verification TEXT)")
        db.executemany("INSERT INTO parts VALUES(?,?,?)", [(1,"jlcparts","31355"),(2,"lcsc_dynamic","541722")])
        selected = {"library_source":"altium","external_part_id":"31355","mfr_part_number":"RC0402FR-074K7L"}
        db.execute("INSERT INTO scan_sessions VALUES('old-scan','imported',1,NULL,?)",
                   (json.dumps({"ai_decision":"exact_match","candidates":[selected]}),))
        db.execute("INSERT INTO scan_sessions VALUES('wrong-snapshot','imported',1,?,?)",
                   (json.dumps({"library_source":"jlcparts","external_part_id":"31355"}),
                    json.dumps({"ai_decision":"exact_match","candidates":[selected]})))
        db.execute("INSERT INTO scan_sessions VALUES('deleted-stock','imported',9,NULL,'{}')")
    digest = hashlib.sha256(main.read_bytes()).hexdigest()
    report = tmp_path / "report.json"
    result = subprocess.run([sys.executable, "scripts/audit_scan_identities.py", "--database", str(main),
                             "--report", str(report)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text())
    assert data["issues"][0]["part_id"] == 1
    assert data["issues"][0]["code"] == "candidate_namespace_mismatch"
    assert data["legacy_source_aliases"] == [{"part_id":2,"external_part_id":"541722"}]
    assert any(issue["code"] == "suspected_numeric_namespace_reuse" for issue in data["issues"])
    assert data["missing_inventory_references"] == [{"scan_id":"deleted-stock","part_id":9,
        "code":"missing_inventory_reference","note":"Inventory may have been deleted; this is not proof of an identity error."}]
    assert hashlib.sha256(main.read_bytes()).hexdigest() == digest
