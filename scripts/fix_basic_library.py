"""Import JLCPCB's no-feeder-fee component classification into PartShelf."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR.parent / "database"
DEFAULT_JLCPARTS_DB = ROOT_DIR / "data" / "libraries" / "jlcparts.db"
DEFAULT_ASSEMBLY_DETAILS = (
    DATABASE_DIR / "jlcpcb-parts-database" / "scraped" / "assembly-details.csv"
)
DEFAULT_COMPONENT_LIST = (
    DATABASE_DIR / "jlcpcb-parts-database" / "scraped" / "ComponentList.csv"
)
DEFAULT_ALTIUM_DB = ROOT_DIR / "data" / "libraries" / "altium_library.db"

FALLBACK_METADATA = {
    109227: {
        "mfr": "LTV-817S-TA1-C",
        "manufacturer": "LITEON",
        "category": "Optoisolators",
        "subcategory": "Phototransistor Output",
        "package": "SMD-4",
        "description": "Optoisolator Transistor Output 5000Vrms 1 Channel SMD-4",
    },
    115450: {
        "mfr": "LTV-217-B-G",
        "manufacturer": "LITEON",
        "category": "Optoisolators",
        "subcategory": "Phototransistor Output",
        "package": "SOP-4",
        "description": "Optoisolator Transistor Output 3750Vrms 1 Channel SOP-4",
    },
    720477: {
        "mfr": "TS-1088-AR02016",
        "manufacturer": "XUNPU",
        "category": "Switches",
        "subcategory": "Tactile Switches",
        "package": "SMD 4x3mm",
        "description": "Tactile switch, SPST, 160gf, 12V 50mA, SMD 4x3mm",
    },
}

ASSEMBLY_FIELDS = (
    "Assembly Type",
    "Assembly Type Batch",
    "Assembly Process",
    "Min Order Qty",
    "Attrition Qty",
    "Special Component Fee",
)


def normalize_lcsc(value: Any) -> int | None:
    text = str(value or "").strip()
    if text[:1].upper() == "C":
        text = text[1:]
    return int(text) if text.isdigit() else None


def infer_category(category: str, package: str, mfr: str, description: str) -> str:
    if category and category.strip():
        return category.strip()

    package_upper = (package or "").upper()
    mfr_upper = (mfr or "").upper()
    description_upper = (description or "").upper()

    if "RES-ARRAY" in package_upper or mfr_upper.startswith("4D03") or "RESISTOR" in description_upper:
        return "Resistors"
    if "CAP" in package_upper or "MLCC" in description_upper or any(
        unit in description_upper for unit in ("PF", "NF", "UF")
    ):
        return "Capacitors - MLCC"
    if "FERRITE" in description_upper or "GZ1608" in mfr_upper or "GZ2012" in mfr_upper:
        return "Ferrite Beads"
    if "INDUCTOR" in description_upper or "SDFL" in mfr_upper:
        return "Inductors"
    if "OPTO" in description_upper or "LTV-" in mfr_upper:
        return "Optoisolators"
    if "SWITCH" in description_upper or "TS-" in mfr_upper:
        return "Switches"
    return ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader)


def _load_source_groups(
    assembly_details_path: Path, component_list_path: Path
) -> dict[int, list[dict[str, str]]]:
    source_groups: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(assembly_details_path):
        lcsc = normalize_lcsc(row.get("lcsc"))
        if lcsc is None:
            continue
        library_type = (row.get("Component Library Type") or "").strip().lower()
        if library_type not in {"base", "expand"}:
            raise ValueError(f"Unexpected library type for C{lcsc}: {library_type!r}")
        fee = (row.get("Special Component Fee") or "").strip()
        if fee and float(fee) != 0:
            raise ValueError(f"C{lcsc} has a nonzero special component fee: {fee}")
        normalized_row = {
            name: (row.get(name) or "").strip() for name in ASSEMBLY_FIELDS
        }
        normalized_row["Component Library Type"] = library_type
        source_groups[lcsc].append(normalized_row)

    listed_ids = {
        lcsc
        for row in _read_csv(component_list_path)
        if (lcsc := normalize_lcsc(row.get("lcsc"))) is not None
    }
    assembly_ids = set(source_groups)
    if assembly_ids != listed_ids:
        missing_from_list = sorted(assembly_ids - listed_ids)
        missing_from_assembly = sorted(listed_ids - assembly_ids)
        raise ValueError(
            "component list does not match assembly details "
            f"(missing from list: {missing_from_list[:8]}, "
            f"missing from assembly details: {missing_from_assembly[:8]})"
        )

    for lcsc, rows in source_groups.items():
        types = {row["Component Library Type"] for row in rows}
        if len(types) != 1:
            raise ValueError(f"C{lcsc} appears as both Basic and Expand")
    return dict(source_groups)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_altium_metadata(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None or not path.exists():
        return {}

    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='altium_components'"
        ).fetchone()
        if not table:
            return {}
        rows = connection.execute(
            """SELECT lcsc_part, category, package, manufacturer, mfr_part_number,
                      lib_reference, description, datasheet_url, parameters_json, basic_part
               FROM altium_components
               WHERE lcsc_part IS NOT NULL AND lcsc_part != ''"""
        )
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            lcsc = normalize_lcsc(row["lcsc_part"])
            if lcsc is None:
                continue
            candidate = dict(row)
            current = result.get(lcsc)
            if current is None or _metadata_score(candidate) > _metadata_score(current):
                result[lcsc] = candidate
        return result
    finally:
        connection.close()


def _metadata_score(row: dict[str, Any]) -> tuple[int, int]:
    fields = ("category", "package", "manufacturer", "mfr_part_number", "description", "parameters_json")
    completeness = sum(bool(row.get(field)) for field in fields)
    return int(row.get("basic_part") or 0), completeness


def _load_lcsc_metadata(
    connection: sqlite3.Connection, lcsc_ids: list[int]
) -> dict[int, dict[str, Any]]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lcsc_components'"
    ).fetchone()
    if not table:
        return {}

    columns = {row[1] for row in connection.execute("PRAGMA table_info(lcsc_components)")}
    wanted = [name for name in ("lcsc", "manufacturer", "attributes", "url_slug") if name in columns]
    if "lcsc" not in wanted:
        return {}
    select_columns = ", ".join(wanted)
    result: dict[int, dict[str, Any]] = {}
    for offset in range(0, len(lcsc_ids), 500):
        batch = lcsc_ids[offset : offset + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"SELECT {select_columns} FROM lcsc_components WHERE lcsc IN ({placeholders})", batch
        )
        for row in rows:
            item = dict(row)
            lcsc = normalize_lcsc(item.get("lcsc"))
            if lcsc is not None:
                result[lcsc] = item
    return result


def _assembly_summary(
    rows: list[dict[str, str]], *, imported: bool = False
) -> tuple[str, str, str]:
    source_rows: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        variant = {key: row.get(key, "") for key in ASSEMBLY_FIELDS}
        signature = tuple(variant[key] for key in ASSEMBLY_FIELDS)
        if signature not in seen:
            source_rows.append(
                {
                    "assembly_type": variant["Assembly Type"],
                    "assembly_type_batch": variant["Assembly Type Batch"],
                    "assembly_process": variant["Assembly Process"],
                    "min_order_qty": variant["Min Order Qty"],
                    "attrition_qty": variant["Attrition Qty"],
                    "special_component_fee": variant["Special Component Fee"],
                }
            )
            seen.add(signature)

    processes = sorted({row["assembly_process"] for row in source_rows if row["assembly_process"]})
    modes = sorted({row["assembly_type"] for row in source_rows if row["assembly_type"]})
    attrition_data = {"source": "assembly-details.csv", "source_rows": source_rows}
    if imported:
        attrition_data["imported_by"] = "fix_basic_library.py"
    attrition = json.dumps(attrition_data, ensure_ascii=False, separators=(",", ":"))
    return ", ".join(processes), ", ".join(modes), attrition


def _make_component_row(
    lcsc: int,
    library_type: str,
    rows: list[dict[str, str]],
    altium: dict[str, Any],
    lcsc_metadata: dict[str, Any],
    current_time: int,
) -> tuple[Any, ...]:
    fallback = FALLBACK_METADATA.get(lcsc, {})
    mfr = (
        altium.get("mfr_part_number")
        or altium.get("lib_reference")
        or fallback.get("mfr", "")
    )
    package = altium.get("package") or fallback.get("package", "")
    manufacturer = (
        altium.get("manufacturer")
        or lcsc_metadata.get("manufacturer")
        or fallback.get("manufacturer", "")
    )
    description = altium.get("description") or fallback.get("description", "")
    category = altium.get("category") or fallback.get("category", "")
    subcategory = fallback.get("subcategory", "")
    category = infer_category(category, package, mfr, description)

    attributes = _json_object(altium.get("parameters_json"))
    if not attributes:
        attributes = _json_object(lcsc_metadata.get("attributes"))
    attributes_json = json.dumps(attributes, ensure_ascii=False, separators=(",", ":"))
    assembly_process, assembly_mode, attrition = _assembly_summary(rows, imported=True)

    return (
        lcsc,
        current_time,
        1,
        1,
        category,
        subcategory,
        mfr,
        package,
        0,
        manufacturer,
        library_type,
        int(library_type == "expand"),
        0,
        description,
        altium.get("datasheet_url") or "",
        -1,  # Inventory is absent from the source files; do not report it as zero stock.
        "",
        attributes_json,
        None,
        "",
        0,
        assembly_process,
        assembly_mode,
        None,
        attrition,
    )


def _existing_source_rows(
    connection: sqlite3.Connection, source_ids: list[int]
) -> dict[int, dict[str, Any]]:
    existing: dict[int, dict[str, Any]] = {}
    for offset in range(0, len(source_ids), 500):
        batch = source_ids[offset : offset + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"SELECT lcsc, stock, attrition FROM jlc_components WHERE lcsc IN ({placeholders})",
            batch,
        )
        existing.update({row["lcsc"]: dict(row) for row in rows})
    return existing


def _create_backup(connection: sqlite3.Connection, backup_path: Path) -> None:
    if backup_path.exists():
        raise FileExistsError(f"Refusing to overwrite database backup: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(backup_path)
    try:
        connection.backup(destination)
    finally:
        destination.close()


def convert_database(
    target_db_path: str | Path,
    assembly_details_path: str | Path,
    component_list_path: str | Path,
    altium_db_path: str | Path | None = None,
    *,
    apply: bool = True,
    backup_path: str | Path | None = None,
) -> dict[str, int | str | None]:
    target_path = Path(target_db_path)
    source_groups = _load_source_groups(Path(assembly_details_path), Path(component_list_path))
    altium = _read_altium_metadata(Path(altium_db_path) if altium_db_path else None)
    ordered_ids = sorted(source_groups)
    base_ids = {
        lcsc
        for lcsc, rows in source_groups.items()
        if rows[0]["Component Library Type"] == "base"
    }
    preferred_ids = set(source_groups) - base_ids

    connection = sqlite3.connect(target_path, timeout=60)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=60000")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jlc_components'"
        ).fetchone()
        if not table:
            raise ValueError(f"Missing jlc_components table in {target_path}")

        existing_rows = _existing_source_rows(connection, ordered_ids)
        existing_ids = set(existing_rows)
        missing_ids = sorted(set(ordered_ids) - existing_ids)
        lcsc_metadata = _load_lcsc_metadata(connection, missing_ids)
        metadata_source_counts = {
            "altium": sum(lcsc in altium for lcsc in missing_ids),
            "lcsc": sum(lcsc not in altium and lcsc in lcsc_metadata for lcsc in missing_ids),
            "unavailable": sum(
                lcsc not in altium and lcsc not in lcsc_metadata for lcsc in missing_ids
            ),
        }
        summary: dict[str, int | str | None] = {
            "source_items": len(source_groups),
            "base_items": len(base_ids),
            "preferred_items": len(preferred_ids),
            "existing": len(existing_ids),
            "updated": len(existing_ids),
            "inserted": len(missing_ids),
            "metadata_from_altium": metadata_source_counts["altium"],
            "metadata_from_lcsc": metadata_source_counts["lcsc"],
            "metadata_unavailable": metadata_source_counts["unavailable"],
            "backup": None,
        }
        if not apply:
            return summary

        if backup_path is not None:
            backup = Path(backup_path)
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup = target_path.with_name(f"{target_path.stem}.before_no_fee_import_{stamp}.bak")
        _create_backup(connection, backup)
        summary["backup"] = str(backup)

        current_time = int(time.time())
        updates = []
        for lcsc in sorted(existing_ids):
            library_type = "base" if lcsc in base_ids else "expand"
            assembly_process, assembly_mode, attrition = _assembly_summary(source_groups[lcsc])
            updates.append((
                library_type,
                int(library_type == "expand"),
                assembly_process,
                assembly_mode,
                existing_rows[lcsc]["stock"],
                attrition,
                lcsc,
            ))

        inserts = [
            _make_component_row(
                lcsc,
                "base" if lcsc in base_ids else "expand",
                source_groups[lcsc],
                altium.get(lcsc, {}),
                lcsc_metadata.get(lcsc, {}),
                current_time,
            )
            for lcsc in missing_ids
        ]

        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """UPDATE jlc_components
                   SET library_type = ?,
                       preferred = ?,
                       assembly_process = COALESCE(NULLIF(assembly_process, ''), ?),
                       assembly_mode = COALESCE(NULLIF(assembly_mode, ''), ?),
                       stock = ?,
                       attrition = CASE WHEN attrition IS NULL OR attrition = '' OR attrition = '{}'
                                        THEN ? ELSE attrition END
                   WHERE lcsc = ?""",
                updates,
            )
            connection.executemany(
                """INSERT INTO jlc_components (
                       lcsc, fetched_at, present, sync_seen, category, subcategory, mfr, package,
                       joints, manufacturer, library_type, preferred, last_on_stock, description,
                       datasheet, stock, price, attributes, rohs, eccn, assembly, assembly_process,
                       assembly_mode, website_component_id, attrition
                   ) VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )""",
                inserts,
            )

            classified = connection.execute(
                "SELECT library_type, preferred, COUNT(*) FROM jlc_components "
                "WHERE lcsc IN (" + ",".join("?" for _ in ordered_ids) + ") "
                "GROUP BY library_type, preferred",
                ordered_ids,
            ).fetchall()
            actual = {(row[0], row[1]): row[2] for row in classified}
            expected = {("base", 0): len(base_ids), ("expand", 1): len(preferred_ids)}
            if actual != expected:
                raise RuntimeError(f"classification validation failed: {actual!r} != {expected!r}")

            check = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"SQLite integrity check failed before commit: {check}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        summary["source_coverage"] = connection.execute(
            "SELECT COUNT(*) FROM jlc_components WHERE lcsc IN ("
            + ",".join("?" for _ in ordered_ids)
            + ")",
            ordered_ids,
        ).fetchone()[0]
        return summary
    finally:
        connection.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_JLCPARTS_DB)
    parser.add_argument("--assembly-details", type=Path, default=DEFAULT_ASSEMBLY_DETAILS)
    parser.add_argument("--component-list", type=Path, default=DEFAULT_COMPONENT_LIST)
    parser.add_argument("--altium-database", type=Path, default=DEFAULT_ALTIUM_DB)
    parser.add_argument("--backup", type=Path, help="Backup destination; never overwritten")
    parser.add_argument("--apply", action="store_true", help="Apply the conversion after preflight")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = convert_database(
        args.database,
        args.assembly_details,
        args.component_list,
        args.altium_database,
        apply=args.apply,
        backup_path=args.backup,
    )
    print("Conversion plan" if not args.apply else "Conversion complete")
    for name, value in summary.items():
        print(f"  {name}: {value}")
    if not args.apply:
        print("No database rows were changed. Pass --apply to run the conversion.")


if __name__ == "__main__":
    main()
