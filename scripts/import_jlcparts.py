import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.common import (
    JLCPARTS_DB_PRIMARY,
    JLCPARTS_DB_FALLBACK,
    DEFAULT_TARGET_DB,
    PartShelfImporter,
)


def import_jlcparts(
    source_db_path: Path,
    target_db_path: Path,
    limit: int = 1000,
    min_stock: int = 5,
    category_filter: str = None,
    include_chips_priority: bool = False,
):
    if not source_db_path.exists():
        if JLCPARTS_DB_FALLBACK.exists():
            print(f"[jlcparts] Primary source not found at {source_db_path}, falling back to {JLCPARTS_DB_FALLBACK}")
            source_db_path = JLCPARTS_DB_FALLBACK
        else:
            raise FileNotFoundError(f"Source database not found at {source_db_path} or {JLCPARTS_DB_FALLBACK}")

    print(f"[jlcparts] Reading from: {source_db_path}")
    print(f"[jlcparts] Target database: {target_db_path}")
    print(f"[jlcparts] Limit: {limit if limit > 0 else 'All'}, Min Stock: {min_stock}")

    src_conn = sqlite3.connect(str(source_db_path))
    src_cur = src_conn.cursor()

    # Query items from jlc_components
    conditions = ["present = 1", "stock >= ?"]
    params = [min_stock]

    if category_filter:
        conditions.append("(category LIKE ? OR subcategory LIKE ?)")
        params.extend([f"%{category_filter}%", f"%{category_filter}%"])

    order_clause = "stock DESC"
    if include_chips_priority:
        order_clause = """
        CASE 
            WHEN category LIKE '%Embedded%' OR category LIKE '%Microcontroller%' THEN 1
            WHEN category LIKE '%Power Management%' OR category LIKE '%PMIC%' THEN 2
            WHEN category LIKE '%Amplifier%' OR category LIKE '%Interface%' THEN 3
            WHEN category LIKE '%Logic%' OR category LIKE '%Memory%' THEN 4
            ELSE 5
        END, stock DESC
        """

    query = f"""
    SELECT lcsc, mfr, category, subcategory, package, manufacturer, description, stock, datasheet
    FROM jlc_components
    WHERE {' AND '.join(conditions)}
    ORDER BY {order_clause}
    """
    if limit > 0:
        query += f" LIMIT {limit}"

    src_cur.execute(query, params)
    rows = src_cur.fetchall()
    src_conn.close()

    print(f"[jlcparts] Fetched {len(rows)} matching components from source.")

    importer = PartShelfImporter(target_db_path)
    start_time = time.time()

    for idx, row in enumerate(rows, 1):
        lcsc, mfr, category, subcategory, package, manufacturer, description, stock, datasheet = row

        part_name = (mfr or "").strip()
        if not part_name:
            part_name = f"C{lcsc}"

        part_type = (subcategory or category or "General").strip()
        pkg = (package or "SMD").strip()
        mfr_name = (manufacturer or "Generic").strip()

        desc = (description or "").strip()
        if not desc and datasheet:
            desc = f"Datasheet: {datasheet}"

        importer.add_part(
            name=part_name,
            description=desc,
            manufacturer=mfr_name,
            package=pkg,
            part_type=part_type,
            quantity=stock or 0,
            disambiguate_suffix=f"C{lcsc}"
        )

        if idx % 2000 == 0:
            importer.commit()
            print(f"[jlcparts] Processed {idx}/{len(rows)} parts (Added: {importer.added_count}, Skipped: {importer.skipped_count})...")

    importer.close()
    elapsed = time.time() - start_time
    print(
        f"[jlcparts] Finished in {elapsed:.2f}s: Added {importer.added_count} parts, "
        f"Skipped {importer.skipped_count} duplicates/empty."
    )
    return importer.added_count, importer.skipped_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import electronic components from jlcparts database into PartShelf")
    parser.add_argument("--source", type=Path, default=JLCPARTS_DB_PRIMARY, help="Path to source sqlite database")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_DB, help="Path to target PartShelf database")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum number of parts to import (0 for all)")
    parser.add_argument("--min-stock", type=int, default=5, help="Minimum stock count to filter")
    parser.add_argument("--category", type=str, default=None, help="Optional category keyword filter")
    parser.add_argument("--priority-chips", action="store_true", help="Prioritize ICs and microcontrollers")

    args = parser.parse_args()
    import_jlcparts(
        source_db_path=args.source,
        target_db_path=args.target,
        limit=args.limit,
        min_stock=args.min_stock,
        category_filter=args.category,
        include_chips_priority=args.priority_chips,
    )
