"""
Import FreeCAD FastenersWB mechanical fastener database into an independent SQLite database (fasteners.db).
Preserves 100% of raw CSV table parameters, parses FastenersCmd command metadata,
and extracts screw hole reference charts without any loss of data.
"""

import os
import sys
import csv
import json
import sqlite3
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = BASE_DIR.parent / "database" / "FreeCAD_FastenersWB"
DEFAULT_FSDATA_DIR = DEFAULT_SOURCE_DIR / "FsData"
DEFAULT_OUTPUT_DB = BASE_DIR / "data" / "libraries" / "fasteners.db"

CATEGORY_GROUP_TRANSLATIONS = {
    "HexHeadGroup": ("Hex Head", "外六角螺栓"),
    "HexagonSocketGroup": ("Hexagon Socket", "内六角螺钉"),
    "HexalobularSocketGroup": ("Hexalobular Socket (Torx)", "梅花槽/星形螺钉"),
    "SlottedGroup": ("Slotted", "一字槽螺钉"),
    "HCrossGroup": ("Phillips Cross", "十字槽螺钉"),
    "NutGroup": ("Nuts", "螺母"),
    "WasherGroup": ("Washers", "垫圈与垫片"),
    "OtherHeadGroup": ("Special Head Bolts", "特殊头型螺栓/螺钉"),
    "ThreadedRodGroup": ("Threaded Rods & Taps", "丝杆与丝锥"),
    "InsertGroup": ("Inserts & Standoffs", "嵌件与PCB隔离柱"),
    "TSlotGroup": ("T-Slot Fasteners", "T型槽与铝型材紧固件"),
    "RetainingRingGroup": ("Retaining Rings", "挡圈与卡簧"),
    "SetScrewGroup": ("Grub/Set Screws", "紧定螺钉/顶丝"),
    "ThumbScrewGroup": ("Thumbscrews", "手拧螺钉"),
    "NailGroup": ("Nails", "圆钉"),
    "PinGroup": ("Pins", "销钉"),
    "WN14xxGroup": ("Self Tapping Screws", "自攻螺钉 (WN14xx)"),
    "GroundScrewGroup": ("Ground Screws", "地脚螺栓"),
}


def create_schema(conn: sqlite3.Connection):
    cursor = conn.cursor()

    # 1. Master catalog of standards and components
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fastener_standards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        standard_code TEXT UNIQUE NOT NULL,
        standard_name TEXT NOT NULL,
        authority TEXT NOT NULL,
        category_group TEXT NOT NULL,
        category_group_zh TEXT NOT NULL,
        description TEXT,
        param_table_name TEXT,
        length_table_name TEXT,
        has_length INTEGER DEFAULT 1,
        source_file TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_std_code ON fastener_standards(standard_code);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_std_category ON fastener_standards(category_group);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_std_authority ON fastener_standards(authority);")

    # 2. Raw table parameters (Key-Value dictionary rows)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fastener_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL,
        row_key TEXT NOT NULL,
        data_json TEXT NOT NULL,
        source_file TEXT NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tbl_name ON fastener_tables(table_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tbl_row_key ON fastener_tables(table_name, row_key);")

    # 3. Table header / column titles metadata
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fastener_table_titles (
        table_name TEXT PRIMARY KEY,
        titles_json TEXT NOT NULL,
        source_file TEXT NOT NULL
    );
    """)

    # 4. Tap hole / Clearance hole reference charts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fastener_hole_charts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chart_type TEXT NOT NULL,
        nominal_dia TEXT NOT NULL,
        hole_diameter REAL NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hole_chart_type ON fastener_hole_charts(chart_type);")

    conn.commit()


def parse_csv_file(filepath: Path) -> Tuple[Dict[str, Dict[str, list]], Dict[str, list]]:
    """
    Parse FastenersWB CSV files according to FSutils.csv2dict specification.
    Supports single or multiple tables within a single file.
    """
    tables: Dict[str, Dict[str, list]] = {}
    titles: Dict[str, list] = {}

    default_table_name = filepath.stem
    with open(filepath, "r", encoding="utf-8", errors="replace") as fp:
        reader = csv.reader(
            fp,
            skipinitialspace=True,
            dialect="unix",
            quoting=csv.QUOTE_NONNUMERIC
        )
        new_table = False
        first_time = True
        cur_table: Dict[str, list] = {}
        cur_names = {default_table_name}

        for row in reader:
            if not row:
                continue
            if len(row) == 1:
                tname = str(row[0]).strip()
                if not new_table:
                    cur_table = {}
                    cur_names = set()
                    new_table = True
                cur_names.add(tname)
                continue

            key = str(row[0]).strip()
            data = list(row[1:])

            if new_table or first_time:
                first_time = False
                new_table = False
                for tname in cur_names:
                    tables[tname] = cur_table
                    titles[tname] = data
                continue

            cur_table[key] = data

    return tables, titles


def extract_command_table(fasteners_cmd_path: Path) -> List[Dict[str, Any]]:
    """
    Extract standard definitions from FastenersCmd.py FSScrewCommandTable.
    """
    if not fasteners_cmd_path.exists():
        return []

    with open(fasteners_cmd_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Locate FSScrewCommandTable = { ... }
    m_start = content.find("FSScrewCommandTable = {")
    if m_start == -1:
        return []

    # Simple line-by-line regex parsing
    items = []
    lines = content[m_start:].splitlines()
    entry_pattern = re.compile(
        r'^\s*["\']([a-zA-Z0-9_\-\.]+)["\']\s*:\s*\(\s*(?:translate\([^,]+,\s*)?["\']([^"\']+)["\']\)?\s*,\s*([a-zA-Z0-9_]+)\s*,\s*([a-zA-Z0-9_]+)'
    )

    for line in lines:
        line_s = line.strip()
        if line_s.startswith("}"):
            break
        match = entry_pattern.match(line_s)
        if match:
            code = match.group(1)
            desc = match.group(2)
            group_var = match.group(3)
            param_group = match.group(4)

            # Determine standard authority
            authority = "Other"
            for auth in ["ISO", "DIN", "ASME", "EN", "GOST", "SAE", "BSPP", "WN"]:
                if code.upper().startswith(auth):
                    authority = auth
                    break
            if "PEM" in code:
                authority = "PEM"
            elif "PCB" in code:
                authority = "Wurth / PCB"

            has_length = 0 if "Nut" in group_var or "Washer" in group_var or "RetainingRing" in group_var else 1

            group_en, group_zh = CATEGORY_GROUP_TRANSLATIONS.get(
                group_var, (group_var.replace("Group", ""), group_var.replace("Group", ""))
            )

            items.append({
                "code": code,
                "name": f"{authority} {code}" if authority in ["ISO", "DIN", "EN", "GOST"] and not code.startswith(authority) else code,
                "authority": authority,
                "category_group": group_en,
                "category_group_zh": group_zh,
                "description": desc,
                "has_length": has_length
            })

    return items


def extract_hole_charts(screw_maker_path: Path) -> List[Tuple[str, str, float]]:
    """
    Extract hole charts from ScrewMaker.py
    """
    if not screw_maker_path.exists():
        return []

    with open(screw_maker_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    charts = []

    def parse_tuple_chart(chart_name: str, chart_type: str):
        pat = re.compile(rf"^{chart_name}\s*=\s*\((.*?)\n\)", re.MULTILINE | re.DOTALL)
        m = pat.search(content)
        if m:
            block = m.group(1)
            entry_pat = re.compile(r'\(\s*["\']([^"\']+)["\']\s*,\s*([\d\.]+)\s*\)')
            for em in entry_pat.finditer(block):
                charts.append((chart_type, em.group(1), float(em.group(2))))

    parse_tuple_chart("FSCScrewHoleChart", "metric_tap_hole")
    parse_tuple_chart("FSC_Inch_ScrewHoleChart", "inch_tap_hole")
    parse_tuple_chart("FSC_DIN7998_ScrewHoleChart", "wood_tap_hole")
    parse_tuple_chart("FSC_ISO1478_ScrewHoleChart", "sheet_metal_tap_hole")
    parse_tuple_chart("FSC_BSPP_ScrewHoleChart", "pipe_tap_hole")

    return charts


def import_fasteners(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_db: Path = DEFAULT_OUTPUT_DB
) -> Dict[str, int]:
    """
    Execute full conversion of FreeCAD FastenersWB into fasteners.db.
    """
    fsdata_dir = source_dir / "FsData"
    cmd_file = source_dir / "FastenersCmd.py"
    screw_maker_file = source_dir / "ScrewMaker.py"

    if not fsdata_dir.exists():
        raise FileNotFoundError(f"FsData directory not found at {fsdata_dir}")

    output_db.parent.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        try:
            output_db.unlink()
        except Exception:
            pass

    conn = sqlite3.connect(output_db)
    create_schema(conn)
    cursor = conn.cursor()

    csv_files = sorted(list(fsdata_dir.glob("*.csv")))
    print(f"Reading {len(csv_files)} CSV definition files from {fsdata_dir}...")

    all_tables: Dict[str, Dict[str, list]] = {}
    all_titles: Dict[str, list] = {}
    table_source_file: Dict[str, str] = {}

    for cf in csv_files:
        tbs, tts = parse_csv_file(cf)
        for tname, tdata in tbs.items():
            all_tables[tname] = tdata
            table_source_file[tname] = cf.name
        for tname, title in tts.items():
            all_titles[tname] = title

    # 1. Insert fastener_table_titles
    title_rows = []
    for tname, titles in all_titles.items():
        title_rows.append((tname, json.dumps(titles, ensure_ascii=False), table_source_file.get(tname, "")))
    cursor.executemany(
        "INSERT OR REPLACE INTO fastener_table_titles (table_name, titles_json, source_file) VALUES (?, ?, ?);",
        title_rows
    )

    # 2. Insert fastener_tables
    data_rows = []
    for tname, tdata in all_tables.items():
        s_file = table_source_file.get(tname, "")
        for row_key, row_val in tdata.items():
            data_rows.append((tname, row_key, json.dumps(row_val, ensure_ascii=False), s_file))

    cursor.executemany(
        "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES (?, ?, ?, ?);",
        data_rows
    )

    # 3. Insert standards from FastenersCmd.py and match tables
    standards = extract_command_table(cmd_file)
    print(f"Extracted {len(standards)} standard definitions from FastenersCmd.py.")

    # Lowercase lookup map for table matching
    lower_tables = {k.lower(): k for k in all_tables.keys()}

    std_rows = []
    seen_codes = set()

    for std in standards:
        code = std["code"]
        seen_codes.add(code.lower())

        # Match param table
        param_table = None
        for candidate in [f"{code}def", code, f"{code.lower()}def", code.lower()]:
            if candidate.lower() in lower_tables:
                param_table = lower_tables[candidate.lower()]
                break

        # Match length table
        length_table = None
        for candidate in [f"{code}length", f"{code.lower()}length"]:
            if candidate.lower() in lower_tables:
                length_table = lower_tables[candidate.lower()]
                break

        s_file = table_source_file.get(param_table, "") if param_table else ""

        std_rows.append((
            code,
            std["name"],
            std["authority"],
            std["category_group"],
            std["category_group_zh"],
            std["description"],
            param_table,
            length_table,
            std["has_length"],
            s_file
        ))

    # Add standalone definition tables that were not listed as interactive GUI commands
    for tname, s_file in table_source_file.items():
        base_name = tname.replace("def", "").replace("length", "")
        if base_name.lower() not in seen_codes and tname.endswith("def"):
            seen_codes.add(base_name.lower())
            auth = "Other"
            for a in ["ISO", "DIN", "ASME", "EN", "GOST", "PEM"]:
                if base_name.upper().startswith(a):
                    auth = a
                    break

            length_match = lower_tables.get(f"{base_name.lower()}length", None)
            std_rows.append((
                base_name,
                base_name,
                auth,
                "General Fasteners",
                "通用标准紧固件",
                f"{base_name} definition standard",
                tname,
                length_match,
                1 if length_match else 0,
                s_file
            ))

    cursor.executemany("""
    INSERT OR REPLACE INTO fastener_standards (
        standard_code, standard_name, authority, category_group, category_group_zh,
        description, param_table_name, length_table_name, has_length, source_file
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, std_rows)

    # 4. Insert hole charts
    charts = extract_hole_charts(screw_maker_file)
    cursor.executemany(
        "INSERT INTO fastener_hole_charts (chart_type, nominal_dia, hole_diameter) VALUES (?, ?, ?);",
        charts
    )

    conn.commit()
    conn.close()

    result = {
        "csv_files": len(csv_files),
        "tables": len(all_tables),
        "rows": len(data_rows),
        "standards": len(std_rows),
        "hole_charts": len(charts),
    }

    print("Fasteners database import completed successfully:")
    print(f"  - Database: {output_db}")
    print(f"  - CSV Files Processed: {result['csv_files']}")
    print(f"  - Tables Created:      {result['tables']}")
    print(f"  - Data Rows Inserted:  {result['rows']:,}")
    print(f"  - Fastener Standards:  {result['standards']}")
    print(f"  - Hole Chart Entries:  {result['hole_charts']}")

    return result


if __name__ == "__main__":
    t0 = time.time()
    import_fasteners()
    print(f"Done in {time.time() - t0:.2f}s")
