"""
Convert KiCad symbol libraries (*.kicad_symdir/*.kicad_sym) into an SQLite database.
Ensures zero data loss by storing both structured metadata and the complete raw S-expression.
"""

import os
import sys
import glob
import json
import sqlite3
import re
import time
from pathlib import Path


DEFAULT_SOURCE_DIR = Path(r"E:\workspace\RadioLabRepoBackend\database\kicad-symbols")
DEFAULT_OUTPUT_DB = Path(r"E:\workspace\RadioLabRepoBackend\PartShelf\data\libraries\kicad_symbols.db")


def create_schema(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kicad_symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        library TEXT NOT NULL,
        name TEXT NOT NULL,
        extends TEXT,
        reference TEXT,
        value TEXT,
        footprint TEXT,
        datasheet TEXT,
        description TEXT,
        keywords TEXT,
        fp_filters TEXT,
        in_bom INTEGER DEFAULT 1,
        on_board INTEGER DEFAULT 1,
        properties_json TEXT,
        raw_sexpr TEXT,
        source_file TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kicad_name ON kicad_symbols(name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kicad_library ON kicad_symbols(library);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kicad_reference ON kicad_symbols(reference);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kicad_value ON kicad_symbols(value);")
    conn.commit()


def parse_kicad_symbol_file(filepath: Path) -> dict:
    lib_name = filepath.parent.name.replace(".kicad_symdir", "")
    
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw_content = f.read()

    sym_match = re.search(r'\(symbol\s+"([^"]+)"', raw_content)
    name = sym_match.group(1) if sym_match else filepath.stem

    extends_match = re.search(r'\(extends\s+"([^"]+)"', raw_content)
    extends = extends_match.group(1) if extends_match else None

    # Parse all properties
    props = {}
    for m in re.finditer(r'\(property\s+"([^"]+)"\s+"([^"]*)"', raw_content):
        props[m.group(1)] = m.group(2)

    # Boolean flags
    in_bom = 0 if '(in_bom no)' in raw_content else 1
    on_board = 0 if '(on_board no)' in raw_content else 1

    rel_path = f"{filepath.parent.name}/{filepath.name}"

    return {
        "library": lib_name,
        "name": name,
        "extends": extends,
        "reference": props.get("Reference", ""),
        "value": props.get("Value", name),
        "footprint": props.get("Footprint", ""),
        "datasheet": props.get("Datasheet", ""),
        "description": props.get("Description", ""),
        "keywords": props.get("ki_keywords", ""),
        "fp_filters": props.get("ki_fp_filters", ""),
        "in_bom": in_bom,
        "on_board": on_board,
        "properties_json": json.dumps(props, ensure_ascii=False),
        "raw_sexpr": raw_content,
        "source_file": rel_path
    }


def convert_kicad(source_dir: Path = DEFAULT_SOURCE_DIR, output_db: Path = DEFAULT_OUTPUT_DB) -> int:
    output_db.parent.mkdir(parents=True, exist_ok=True)

    if output_db.exists():
        output_db.unlink()

    conn = sqlite3.connect(str(output_db))
    create_schema(conn)

    cursor = conn.cursor()
    insert_sql = """
    INSERT INTO kicad_symbols (
        library, name, extends, reference, value, footprint, datasheet,
        description, keywords, fp_filters, in_bom, on_board,
        properties_json, raw_sexpr, source_file
    ) VALUES (
        :library, :name, :extends, :reference, :value, :footprint, :datasheet,
        :description, :keywords, :fp_filters, :in_bom, :on_board,
        :properties_json, :raw_sexpr, :source_file
    )
    """

    sym_files = list(source_dir.glob("*.kicad_symdir/*.kicad_sym"))
    print(f"Found {len(sym_files)} KiCad symbol files across {len(list(source_dir.glob('*.kicad_symdir')))} libraries.")

    start_time = time.time()
    batch = []
    total_inserted = 0
    batch_size = 1000

    for i, sym_path in enumerate(sym_files, 1):
        parsed = parse_kicad_symbol_file(sym_path)
        batch.append(parsed)

        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            conn.commit()
            total_inserted += len(batch)
            batch.clear()
            if total_inserted % 5000 == 0:
                print(f"  Imported {total_inserted}/{len(sym_files)} symbols...")

    if batch:
        cursor.executemany(insert_sql, batch)
        conn.commit()
        total_inserted += len(batch)
        batch.clear()

    conn.close()
    elapsed = time.time() - start_time
    print(f"KiCad symbols conversion completed: {total_inserted} symbols imported in {elapsed:.2f}s -> {output_db}")
    return total_inserted


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE_DIR
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_DB
    convert_kicad(src, out)
