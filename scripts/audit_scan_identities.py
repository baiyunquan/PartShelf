"""Read-only audit of historical scan/catalog references. Never repairs ambiguous IDs."""
import argparse
import json
from pathlib import Path
import sqlite3


def identity(item):
    if not isinstance(item, dict):
        return None
    row = {**(item.get("raw_item") or {}), **item}
    source = row.get("library_source") or row.get("source")
    source = "jlcparts" if source == "lcsc_dynamic" else source
    if not source:
        source = "jlcparts" if row.get("lcsc") else "altium" if row.get("lib_reference") else None
    key = row.get("external_part_id") or (row.get("lcsc") if source == "jlcparts" else row.get("id"))
    if not source or key is None:
        return None
    return {"library_source": source, "external_part_id": str(key).lstrip("Cc") if source == "jlcparts" else str(key)}


def decode(value):
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def audit(database):
    path = Path(database).resolve()
    report = {"database": str(path), "read_only": True, "legacy_source_aliases": [], "issues": [],
              "missing_inventory_references": [], "scans_checked": 0}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        parts = {row["id"]: dict(row) for row in db.execute("SELECT id,library_source,external_part_id FROM parts ORDER BY id")}
        for part in parts.values():
            if part["library_source"] == "lcsc_dynamic":
                report["legacy_source_aliases"].append({"part_id":part["id"],"external_part_id":part["external_part_id"]})
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "scan_sessions" not in tables:
            return report
        for row in db.execute("SELECT id,part_id,component,verification FROM scan_sessions WHERE status='imported' ORDER BY id"):
            report["scans_checked"] += 1
            part = parts.get(row["part_id"])
            if part is None:
                report["missing_inventory_references"].append({"scan_id":row["id"],"part_id":row["part_id"],
                    "code":"missing_inventory_reference", "note":"Inventory may have been deleted; this is not proof of an identity error."})
                continue
            current = identity(part)
            selected = identity(decode(row["component"]))
            verification = decode(row["verification"])
            candidates = verification.get("candidates") or []
            evidence = "snapshot_namespace_mismatch"
            if selected is None and verification.get("ai_decision") == "exact_match" and candidates:
                selected = identity(candidates[0])
                evidence = "candidate_namespace_mismatch"
            if selected and current != selected:
                report["issues"].append({"scan_id":row["id"], "part_id":part["id"], "code":evidence,
                    "inventory_identity":current, "scan_evidence_identity":selected, "action":"manual_review"})
            elif current and verification.get("ai_decision") == "exact_match" and candidates:
                proposed = identity(candidates[0])
                if (proposed and proposed["library_source"] != current["library_source"]
                        and proposed["external_part_id"] == current["external_part_id"]):
                    report["issues"].append({"scan_id":row["id"], "part_id":part["id"],
                        "code":"suspected_numeric_namespace_reuse", "inventory_identity":current,
                        "scan_evidence_identity":proposed, "action":"manual_review",
                        "note":"A deliberate manual override is possible; do not repair without checking the photograph."})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Existing SQLite business database; opened read-only")
    parser.add_argument("--report", type=Path, help="JSON report path; otherwise print JSON")
    args = parser.parse_args()
    report = audit(args.database)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
