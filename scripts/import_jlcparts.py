"""
Import and prepare the JLCParts database into PartShelf's data/libraries/ directory.
Preserves all raw data tables (jlc_components, lcsc_components, meta) with zero data loss,
and creates high-performance indexes for fast searching.
"""

import os
import sys
import shutil
import sqlite3
import time
from pathlib import Path


DEFAULT_SOURCE_DB = Path(r"E:\workspace\RadioLabRepoBackend\database\jlcparts\cache.sqlite3")
DEFAULT_OUTPUT_DB = Path(r"E:\workspace\RadioLabRepoBackend\PartShelf\data\libraries\jlcparts.db")


def import_jlcparts(source_db: Path = DEFAULT_SOURCE_DB, output_db: Path = DEFAULT_OUTPUT_DB) -> int:
    output_db.parent.mkdir(parents=True, exist_ok=True)

    if not source_db.exists():
        print(f"Error: Source database does not exist: {source_db}", file=sys.stderr)
        return 0

    print(f"Importing JLCParts database from: {source_db} ({source_db.stat().st_size / (1024*1024):.1f} MB)")
    start_time = time.time()

    # If output_db does not exist or has different size, copy from source
    if not output_db.exists() or output_db.stat().st_size != source_db.stat().st_size:
        print(f"Copying to {output_db}...")
        shutil.copy2(source_db, output_db)
        print("Copy finished.")

    # Create helpful indexes on output_db for ultra-fast queries
    print("Ensuring query indexes on JLCParts database...")
    conn = sqlite3.connect(str(output_db))
    cursor = conn.cursor()

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jlc_mfr ON jlc_components(mfr);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jlc_package ON jlc_components(package);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jlc_category ON jlc_components(category, subcategory);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jlc_stock ON jlc_components(stock);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_lcsc_comp_lcsc ON lcsc_components(lcsc);")
    conn.commit()

    cursor.execute("SELECT count(*) FROM jlc_components;")
    total_components = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM lcsc_components;")
    total_lcsc = cursor.fetchone()[0]

    conn.close()
    elapsed = time.time() - start_time
    print(f"JLCParts database ready: {total_components} components, {total_lcsc} LCSC records in {elapsed:.2f}s -> {output_db}")
    return total_components


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE_DB
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_DB
    import_jlcparts(src, out)
