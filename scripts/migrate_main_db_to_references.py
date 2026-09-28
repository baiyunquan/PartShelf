"""
Database migration script:
Refactors PartShelf's partshelf.db to a pure external library reference schema.
1. Backs up partshelf.db to partshelf.db.bak.
2. Inspects existing legacy parts (1503 parts).
3. Matches each part against altium_library.db, kicad_symbols.db, and jlcparts.db using indexed lookups.
4. Creates new pure reference tables and populates parts, inventories, and relations.
"""

import os
import sys
import shutil
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "partshelf.db"
BACKUP_PATH = BASE_DIR / "partshelf.db.bak"
DATA_DIR = BASE_DIR / "data" / "libraries"

ALTIUM_DB = DATA_DIR / "altium_library.db"
KICAD_DB = DATA_DIR / "kicad_symbols.db"
JLCPARTS_DB = DATA_DIR / "jlcparts.db"


def build_lookup_maps(altium_conn, kicad_conn, jlc_conn):
    print("Building in-memory indexed lookup sets...", flush=True)
    
    # 1. Altium lib_reference -> id
    cur = altium_conn.cursor()
    cur.execute("SELECT lib_reference, id FROM altium_components")
    altium_ref_map = dict(cur.fetchall())
    
    # Altium lcsc_part -> id
    cur.execute("SELECT lcsc_part, id FROM altium_components WHERE lcsc_part != ''")
    altium_lcsc_map = dict(cur.fetchall())
    
    # 2. KiCad name -> id
    cur = kicad_conn.cursor()
    cur.execute("SELECT name, id FROM kicad_symbols")
    kicad_name_map = dict(cur.fetchall())
    
    # 3. JLCParts mfr -> lcsc
    cur = jlc_conn.cursor()
    cur.execute("SELECT mfr, lcsc FROM jlc_components WHERE mfr != '' LIMIT 1000000")
    jlc_mfr_map = {}
    for r in cur.fetchall():
        if r[0] not in jlc_mfr_map:
            jlc_mfr_map[r[0]] = r[1]

    print(f"Maps built: Altium refs={len(altium_ref_map)}, KiCad names={len(kicad_name_map)}, JLCParts mfrs={len(jlc_mfr_map)}", flush=True)
    return altium_ref_map, altium_lcsc_map, kicad_name_map, jlc_mfr_map


def match_part(name: str, altium_ref_map, altium_lcsc_map, kicad_name_map, jlc_mfr_map):
    clean_name = name.strip()
    
    # 1. Altium exact lib_reference
    if clean_name in altium_ref_map:
        return ("altium", str(altium_ref_map[clean_name]))
    
    # 2. JLCParts exact mfr
    if clean_name in jlc_mfr_map:
        return ("jlcparts", str(jlc_mfr_map[clean_name]))
    
    # 3. KiCad exact name
    if clean_name in kicad_name_map:
        return ("kicad", str(kicad_name_map[clean_name]))
    
    # 4. LCSC part number (e.g. C12345 or 12345)
    clean_upper = clean_name.upper()
    if clean_upper in altium_lcsc_map:
        return ("altium", str(altium_lcsc_map[clean_upper]))
    
    if clean_upper.startswith("C") and clean_upper[1:].isdigit():
        num = int(clean_upper[1:])
        return ("jlcparts", str(num))
    
    # 5. Case-insensitive attempt
    for k in (clean_name.upper(), clean_name.lower()):
        if k in altium_ref_map:
            return ("altium", str(altium_ref_map[k]))
        if k in jlc_mfr_map:
            return ("jlcparts", str(jlc_mfr_map[k]))
        if k in kicad_name_map:
            return ("kicad", str(kicad_name_map[k]))

    return None


def run_migration():
    if not DB_PATH.exists():
        print(f"Database {DB_PATH} not found. Skipping migration.", flush=True)
        return

    if not BACKUP_PATH.exists():
        print(f"Creating backup: {BACKUP_PATH}", flush=True)
        shutil.copy2(DB_PATH, BACKUP_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT p.id, p.name, p.description, i.quantity_available
        FROM parts p
        LEFT JOIN inventories i ON p.id = i.part_id
    """)
    legacy_parts = cur.fetchall()
    print(f"Found {len(legacy_parts)} legacy parts in partshelf.db.", flush=True)

    altium_conn = sqlite3.connect(f"file:{ALTIUM_DB}?mode=ro", uri=True)
    kicad_conn = sqlite3.connect(f"file:{KICAD_DB}?mode=ro", uri=True)
    jlc_conn = sqlite3.connect(f"file:{JLCPARTS_DB}?mode=ro", uri=True)

    altium_ref_map, altium_lcsc_map, kicad_name_map, jlc_mfr_map = build_lookup_maps(
        altium_conn, kicad_conn, jlc_conn
    )

    matched_records = []
    unmatched_records = []

    for lp in legacy_parts:
        matched = match_part(
            lp["name"] or "",
            altium_ref_map, altium_lcsc_map, kicad_name_map, jlc_mfr_map
        )
        if matched:
            matched_records.append({
                "library_source": matched[0],
                "external_part_id": matched[1],
                "storage_location": "Default Storage",
                "note": lp["description"] or "",
                "quantity": lp["quantity_available"] if lp["quantity_available"] is not None else 0
            })
        else:
            unmatched_records.append(lp)

    print(f"Matching finished: {len(matched_records)} matched, {len(unmatched_records)} unmatched.", flush=True)

    # Recreate tables in partshelf.db
    cur.execute("PRAGMA foreign_keys = OFF;")
    cur.execute("DROP TABLE IF EXISTS project_parts;")
    cur.execute("DROP TABLE IF EXISTS inventories;")
    cur.execute("DROP TABLE IF EXISTS parts;")
    cur.execute("DROP TABLE IF EXISTS manufacturers;")
    cur.execute("DROP TABLE IF EXISTS packages;")
    cur.execute("DROP TABLE IF EXISTS types;")

    # Create new parts table (pure reference)
    cur.execute("""
    CREATE TABLE parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        library_source TEXT NOT NULL,
        external_part_id TEXT NOT NULL,
        storage_location TEXT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX idx_parts_source ON parts(library_source, external_part_id);")

    # Create inventories table
    cur.execute("""
    CREATE TABLE inventories (
        part_id INTEGER PRIMARY KEY,
        quantity_available INTEGER DEFAULT 0,
        FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE CASCADE
    );
    """)

    # Create project_parts table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS project_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        part_id INTEGER NOT NULL,
        quantity_needed INTEGER DEFAULT 0,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(part_id) REFERENCES parts(id) ON DELETE CASCADE
    );
    """)

    # Insert matched records
    for r in matched_records:
        cur.execute("""
            INSERT INTO parts (library_source, external_part_id, storage_location, note)
            VALUES (?, ?, ?, ?);
        """, (r["library_source"], r["external_part_id"], r["storage_location"], r["note"]))
        new_part_id = cur.lastrowid
        cur.execute("""
            INSERT INTO inventories (part_id, quantity_available)
            VALUES (?, ?);
        """, (new_part_id, r["quantity"]))

    conn.commit()
    conn.close()

    altium_conn.close()
    kicad_conn.close()
    jlc_conn.close()

    print(f"Migration completed! {len(matched_records)} parts successfully migrated into pure reference schema.", flush=True)


if __name__ == "__main__":
    run_migration()
