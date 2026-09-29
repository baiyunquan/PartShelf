"""
Import mechanical component database into an independent SQLite database (fasteners.db).
Integrates:
1. FreeCAD FastenersWB (234 standards: screws, bolts, nuts, washers, standoffs, hole charts)
2. Whole-Spec Database (40 standards: power transmission, bearings, gears, motors, aluminum profiles, structural steel, square tubes, plates, pipes, torque & wrench assembly guides)

Preserves 100% of raw table parameters, parses FastenersCmd command metadata,
and supports multi-domain organization (Fasteners, Power Transmission, Structural Materials).
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
DEFAULT_WHOLE_SPEC_DB = BASE_DIR.parent / "database" / "whole-spec" / "data" / "whole_spec.db"

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

WHOLE_SPEC_MAPPINGS = {
    # Power Transmission - Bearings
    "deep-groove-ball-bearing": ("KS_B_2001_DEEP_GROOVE", "深沟球轴承 (Deep Groove Ball Bearing 6000~6310)", "BearingGroup", "轴承", "KS", 0),
    "tapered-roller-bearing": ("ISO_355_TAPERED_ROLLER", "圆锥滚子轴承 (Tapered Roller Bearing 30202~30208)", "BearingGroup", "轴承", "ISO", 0),
    "cylindrical-roller-bearing": ("KS_B_2001_CYLINDRICAL_ROLLER", "圆柱滚子轴承 (Cylindrical Roller Bearing NU204~NU212)", "BearingGroup", "轴承", "KS", 0),
    "self-aligning-ball-bearing": ("KS_B_2001_SELF_ALIGNING", "调心球轴承 (Self-Aligning Ball Bearing 1204~1210)", "BearingGroup", "轴承", "KS", 0),
    "thrust-ball-bearing": ("KS_B_2001_THRUST_BALL", "推力球轴承 (Thrust Ball Bearing 51100~51110)", "BearingGroup", "轴承", "KS", 0),
    "angular-contact-ball-bearing": ("KS_B_2023_ANGULAR_CONTACT", "角接触球轴承 (Angular Contact Bearing 7200~7210)", "BearingGroup", "轴承", "KS", 0),
    "speed-temp-factor": ("ISO_281_SPEED_TEMP_FACTOR", "轴承速度与温度修正系数 (Bearing Speed & Temp Factors)", "BearingGroup", "轴承", "ISO", 0),
    "reliability-factor": ("ISO_281_RELIABILITY_FACTOR", "轴承可靠度系数 (Bearing Reliability Factor)", "BearingGroup", "轴承", "ISO", 0),
    # Power Transmission - Gears
    "spur-gear": ("KS_B_1401_SPUR_GEAR", "渐开线直齿轮 (Spur Gear M0.5~M6)", "GearGroup", "齿轮", "KS", 0),
    "helical-gear": ("KS_B_1401_HELICAL_GEAR", "斜齿轮 (Helical Gear M1~M3)", "GearGroup", "齿轮", "KS", 0),
    "bevel-gear": ("KS_B_1401_BEVEL_GEAR", "标准锥齿轮 (Bevel Gear M1~M3)", "GearGroup", "齿轮", "KS", 0),
    "worm-gear": ("KS_B_1401_WORM_GEAR", "蜗轮与蜗杆 (Worm Gear M1~M3)", "GearGroup", "齿轮", "KS", 0),
    "rack-gear": ("KS_B_1401_RACK_GEAR", "工业齿条 (Rack Gear M1~M5)", "GearGroup", "齿轮", "KS", 0),
    "internal-gear": ("KS_B_1401_INTERNAL_GEAR", "内齿轮 (Internal Gear M1~M3)", "GearGroup", "齿轮", "KS", 0),
    # Power Transmission - Motors
    "stepper-motor": ("NEMA_STEPPER_MOTOR", "步进电机 (Stepper Motor NEMA11~NEMA42)", "MotorGroup", "电机与驱动", "NEMA", 0),
    "ac-servo-motor": ("JIS_C_4034_AC_SERVO", "交流伺服电机 (AC Servo Motor 100W~5kW)", "MotorGroup", "电机与驱动", "JIS", 0),
    "bldc-motor": ("JIS_C_4034_BLDC_MOTOR", "无刷直流电机 (BLDC Motor 24V~48V)", "MotorGroup", "电机与驱动", "JIS", 0),
    # Power Transmission - Keys & Seals
    "parallel-key": ("KS_B_1311_PARALLEL_KEY", "平键 (Parallel Key 2×2~20×12)", "KeyGroup", "键与传动销", "KS", 0),
    "woodruff-key": ("KS_B_1311_WOODRUFF_KEY", "半月键 (Woodruff Key 2×6.5~6×19)", "KeyGroup", "键与传动销", "KS", 0),
    "sc-oil-seal": ("KS_B_2804_SC_OIL_SEAL", "SC型旋转油封 (SC Oil Seal NBR)", "OilSealGroup", "油封与密封", "KS", 0),
    "tc-oil-seal": ("KS_B_2804_TC_OIL_SEAL", "TC型双唇骨架油封 (TC Oil Seal NBR)", "OilSealGroup", "油封与密封", "KS", 0),
    # Structural Materials - Aluminum Profiles
    "aluminum-profile": ("JIS_H_4100_ALU_PROFILE", "工业铝型材标准型 (Aluminum Profile 2020~100100)", "ProfileGroup", "铝型材与配件", "JIS", 1),
    "aluminum-profile-light": ("JIS_H_4100_ALU_PROFILE_LIGHT", "工业铝型材轻型 (Aluminum Profile Light 4040L)", "ProfileGroup", "铝型材与配件", "JIS", 1),
    # Structural Materials - Square & Rectangular Tubes
    "square": ("KS_D_3568_SQUARE_TUBE", "方形钢管/方管 (Square Steel Tube □20×20~HSS 12×12)", "SquareTubeGroup", "方管与矩形管", "KS", 1),
    "rectangular": ("KS_D_3568_RECT_TUBE", "矩形钢管/扁管 (Rectangular Steel Tube 30×20~HSS 12×8)", "SquareTubeGroup", "方管与矩形管", "KS", 1),
    # Structural Materials - Structural Steel Sections
    "h-beam": ("KS_D_3502_H_BEAM", "热轧H型钢 (H-Beam 100×100~600×200)", "StructuralSteelGroup", "型钢构件", "KS", 1),
    "equal-angle": ("KS_D_3502_EQUAL_ANGLE", "热轧等边角钢 (Equal Angle L25×25~L150×150)", "StructuralSteelGroup", "型钢构件", "KS", 1),
    "unequal-angle": ("KS_D_3502_UNEQUAL_ANGLE", "热轧不等边角钢 (Unequal Angle L75×50~L150×90)", "StructuralSteelGroup", "型钢构件", "KS", 1),
    "channel": ("KS_D_3502_CHANNEL", "热轧槽钢 (Channel C75×40~C380×100)", "StructuralSteelGroup", "型钢构件", "KS", 1),
    "ct-beam": ("KS_D_3502_CT_BEAM", "热轧CT型钢 (CT-Beam CT100×100~CT200×200)", "StructuralSteelGroup", "型钢构件", "KS", 1),
    "i-beam": ("KS_D_3502_I_BEAM", "热轧工字钢 (I-Beam I100~I400)", "StructuralSteelGroup", "型钢构件", "KS", 1),
    # Structural Materials - Pipes
    "carbon-steel-pipe": ("KS_D_3507_CARBON_STEEL_PIPE", "配管用碳钢管 (Carbon Steel Pipe 15A~150A)", "PipeGroup", "工业管材", "KS", 1),
    "stainless-steel-pipe": ("KS_D_3576_STAINLESS_PIPE", "配管用不锈钢管 (Stainless Steel Pipe 6A~80A)", "PipeGroup", "工业管材", "KS", 1),
    # Structural Materials - Plates
    "hot-rolled-plate": ("KS_D_3503_HOT_ROLLED_PLATE", "热轧钢板 (Hot Rolled Steel Plate SS400/SPHC)", "PlateGroup", "金属板材", "KS", 0),
    "cold-rolled-plate": ("KS_D_3512_COLD_ROLLED_PLATE", "冷轧钢板 (Cold Rolled Steel Plate SPCC)", "PlateGroup", "金属板材", "KS", 0),
    "stainless-plate": ("KS_D_3698_STAINLESS_PLATE", "不锈钢板 (Stainless Plate SUS304/SUS316)", "PlateGroup", "金属板材", "KS", 0),
    "aluminum-plate": ("KS_D_6701_ALUMINUM_PLATE", "铝合金板 (Aluminum Plate A5052/A6061)", "PlateGroup", "金属板材", "KS", 0),
    "checkered-plate": ("KS_D_3503_CHECKERED_PLATE", "花纹钢板 (Checkered Steel Plate)", "PlateGroup", "金属板材", "KS", 0),
    "copper-plate": ("KS_D_5201_COPPER_PLATE", "纯铜板 (Copper Plate C1100)", "PlateGroup", "金属板材", "KS", 0),
    "brass-plate": ("KS_D_5201_BRASS_PLATE", "黄铜板 (Brass Plate C2801)", "PlateGroup", "金属板材", "KS", 0),
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
        domain TEXT DEFAULT 'fasteners',
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_std_domain ON fastener_standards(domain);")
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

    # 5. Fastener Assembly Guides (Torque specs and tool/wrench clearance)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fastener_assembly_guides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nominal TEXT UNIQUE NOT NULL,
        stress_area REAL,
        preload_8_8 REAL,
        dry_torque_8_8 REAL,
        lube_torque_8_8 REAL,
        preload_10_9 REAL,
        dry_torque_10_9 REAL,
        lube_torque_10_9 REAL,
        preload_12_9 REAL,
        dry_torque_12_9 REAL,
        lube_torque_12_9 REAL,
        hex_wrench_af REAL,
        socket_size REAL,
        hex_key REAL,
        socket_head_dia REAL,
        socket_head_height REAL,
        raw_json TEXT
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_guide_nominal ON fastener_assembly_guides(nominal);")

    conn.commit()


def parse_csv_file(filepath: Path) -> Tuple[Dict[str, Dict[str, list]], Dict[str, list]]:
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
                clean_titles = [str(x).strip() for x in data if str(x).strip()]
                for name in cur_names:
                    tables[name] = cur_table
                    titles[name] = clean_titles
                continue

            cur_table[key] = data

    return tables, titles


def extract_command_table(cmd_file: Path) -> List[Dict[str, Any]]:
    if not cmd_file.exists():
        return []

    with open(cmd_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Extract FastenersStandardMap if present
    std_map = {}
    m_map = re.search(r"FastenersStandardMap\s*=\s*\{(.*?)\}", content, re.DOTALL)
    if m_map:
        for entry in re.finditer(r'["\']([^"\']+)["\']\s*:\s*["\']([^"\']+)["\']', m_map.group(1)):
            std_map[entry.group(1)] = entry.group(2)

    pattern = re.compile(
        r'["\']([A-Za-z0-9_\.]+)["\']\s*:\s*\(\s*translate\([^,]+,\s*["\']([^"\']+)["\']\)\s*,\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)',
        re.MULTILINE
    )

    items = []
    for m in pattern.finditer(content):
        code = m.group(1).strip()
        desc = m.group(2).strip()
        group_var = m.group(3).strip()
        params = m.group(4).strip()
        has_length = 1 if "L" in params else 0

        authority = std_map.get(code)
        if not authority:
            for a in ["ISO", "DIN", "EN", "ASME", "GOST", "PEM", "SAE"]:
                if code.upper().startswith(a):
                    authority = a
                    break
        if not authority:
            authority = "Other"

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


def import_whole_spec_components(cursor: sqlite3.Cursor, whole_spec_db: Path) -> Tuple[int, int]:
    """
    Imports Whole-Spec (power transmission, structural materials, assembly guides)
    into fasteners.db without downloading any 3D models.
    """
    if not whole_spec_db.exists():
        print(f"[Whole-Spec] Database not found at {whole_spec_db}, skipping.")
        return 0, 0

    conn_ws = sqlite3.connect(whole_spec_db)
    conn_ws.row_factory = sqlite3.Row
    cur_ws = conn_ws.cursor()

    cur_ws.execute("""
    SELECT s.id, s.category_key, s.subcategory, s.slug, s.title, s.name_zh, s.name_en, s.standards_json, s.total_items
    FROM specs s
    WHERE s.category_key IN ('power_transmission', 'structural_materials')
      AND s.total_items > 0
      AND s.slug != s.subcategory
      AND s.slug != 'step'
    ORDER BY s.category_key, s.subcategory, s.id
    """)
    specs = cur_ws.fetchall()

    imported_specs = 0
    imported_rows = 0

    for s in specs:
        slug = s["slug"]
        mapping = WHOLE_SPEC_MAPPINGS.get(slug)
        if not mapping:
            continue

        std_code, std_name, cat_group, cat_group_zh, authority, has_length = mapping
        domain = s["category_key"]

        # Fetch table headers and items from whole_spec.db
        cur_ws.execute("""
        SELECT t.id, t.headers_json, t.rows_count
        FROM spec_tables t
        WHERE t.spec_id = ?
        LIMIT 1
        """, (s["id"],))
        table_meta = cur_ws.fetchone()
        if not table_meta:
            continue

        headers = json.loads(table_meta["headers_json"])
        # Param titles: First column is row_key (Nominal), remaining are parameter titles
        titles = headers[1:] if len(headers) > 1 else headers
        param_table_name = f"table_{std_code}"
        cursor.execute(
            "INSERT OR REPLACE INTO fastener_table_titles (table_name, titles_json, source_file) VALUES (?, ?, ?);",
            (param_table_name, json.dumps(titles, ensure_ascii=False), f"whole-spec:{slug}")
        )

        # Fetch items
        cur_ws.execute("""
        SELECT i.nominal, i.raw_row_json
        FROM spec_items i
        WHERE i.spec_id = ? AND i.table_id = ?
        """, (s["id"], table_meta["id"]))

        table_rows = cur_ws.fetchall()
        for r in table_rows:
            nom = r["nominal"]
            raw_vals = json.loads(r["raw_row_json"])
            # Remove nominal from value list if present
            vals = raw_vals[1:] if len(raw_vals) > 1 else raw_vals
            cursor.execute(
                "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES (?, ?, ?, ?);",
                (param_table_name, nom, json.dumps(vals, ensure_ascii=False), f"whole-spec:{slug}")
            )
            imported_rows += 1

        # If cut-to-length material, populate a length table
        length_table_name = None
        if has_length:
            length_table_name = f"length_{std_code}"
            std_lengths = ["100", "200", "300", "500", "800", "1000", "1200", "1500", "2000"]
            cursor.execute(
                "INSERT OR REPLACE INTO fastener_table_titles (table_name, titles_json, source_file) VALUES (?, ?, ?);",
                (length_table_name, json.dumps(["L (mm)"], ensure_ascii=False), "whole-spec:standard_lengths")
            )
            # Add length entries for each nominal
            for r in table_rows:
                nom = r["nominal"]
                cursor.execute(
                    "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES (?, ?, ?, ?);",
                    (length_table_name, nom, json.dumps(std_lengths, ensure_ascii=False), "whole-spec:standard_lengths")
                )

        # Insert into fastener_standards
        cursor.execute("""
        INSERT OR REPLACE INTO fastener_standards (
            standard_code, standard_name, authority, domain, category_group, category_group_zh,
            description, param_table_name, length_table_name, has_length, source_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            std_code,
            std_name,
            authority,
            domain,
            cat_group,
            cat_group_zh,
            s["title"],
            param_table_name,
            length_table_name,
            has_length,
            f"whole-spec:{slug}"
        ))
        imported_specs += 1

    # Populate Fastener Assembly Guides from Whole-Spec torque & wrench tables
    torques = {}
    for grade in ["grade-8-8", "grade-10-9", "grade-12-9"]:
        cur_ws.execute("""
        SELECT i.nominal, i.raw_row_json 
        FROM spec_items i 
        JOIN specs s ON i.spec_id = s.id 
        WHERE s.slug = ?
        """, (grade,))
        for nom, raw in cur_ws.fetchall():
            row = json.loads(raw)
            if nom not in torques:
                try:
                    sa = float(row[1])
                except Exception:
                    sa = None
                torques[nom] = {"nominal": nom, "stress_area": sa}
            gkey = grade.replace("grade-", "")
            try:
                torques[nom][f"dry_{gkey}"] = float(row[3])
                torques[nom][f"lube_{gkey}"] = float(row[4])
                torques[nom][f"preload_{gkey}"] = float(row[2])
            except Exception:
                pass

    cur_ws.execute("""
    SELECT i.nominal, i.raw_row_json 
    FROM spec_items i 
    JOIN specs s ON i.spec_id = s.id 
    WHERE s.slug = 'hex-bolt'
    """)
    for nom, raw in cur_ws.fetchall():
        row = json.loads(raw)
        if nom in torques:
            try:
                torques[nom]["hex_wrench_af"] = float(row[1])
                torques[nom]["socket_size"] = float(row[2])
            except Exception:
                pass

    cur_ws.execute("""
    SELECT i.nominal, i.raw_row_json 
    FROM spec_items i 
    JOIN specs s ON i.spec_id = s.id 
    WHERE s.slug = 'socket-cap'
    """)
    for nom, raw in cur_ws.fetchall():
        row = json.loads(raw)
        if nom in torques:
            try:
                torques[nom]["hex_key"] = float(row[1])
                torques[nom]["socket_head_dia"] = float(row[2])
                torques[nom]["socket_head_height"] = float(row[3])
            except Exception:
                pass

    for nom, gdata in torques.items():
        cursor.execute("""
        INSERT OR REPLACE INTO fastener_assembly_guides (
            nominal, stress_area,
            preload_8_8, dry_torque_8_8, lube_torque_8_8,
            preload_10_9, dry_torque_10_9, lube_torque_10_9,
            preload_12_9, dry_torque_12_9, lube_torque_12_9,
            hex_wrench_af, socket_size, hex_key, socket_head_dia, socket_head_height, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            nom,
            gdata.get("stress_area"),
            gdata.get("preload_8-8"),
            gdata.get("dry_8-8"),
            gdata.get("lube_8-8"),
            gdata.get("preload_10-9"),
            gdata.get("dry_10-9"),
            gdata.get("lube_10-9"),
            gdata.get("preload_12-9"),
            gdata.get("dry_12-9"),
            gdata.get("lube_12-9"),
            gdata.get("hex_wrench_af"),
            gdata.get("socket_size"),
            gdata.get("hex_key"),
            gdata.get("socket_head_dia"),
            gdata.get("socket_head_height"),
            json.dumps(gdata, ensure_ascii=False)
        ))

    conn_ws.close()
    return imported_specs, imported_rows


def import_fasteners(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_db: Path = DEFAULT_OUTPUT_DB,
    whole_spec_db: Path = DEFAULT_WHOLE_SPEC_DB
) -> Dict[str, int]:
    """
    Execute full conversion of FreeCAD FastenersWB and Whole-Spec into fasteners.db.
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
            "fasteners",
            std["category_group"],
            std["category_group_zh"],
            std["description"],
            param_table,
            length_table,
            std["has_length"],
            s_file
        ))

    # Add standalone definition tables
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
                "fasteners",
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
        standard_code, standard_name, authority, domain, category_group, category_group_zh,
        description, param_table_name, length_table_name, has_length, source_file
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, std_rows)

    # 4. Insert hole charts
    charts = extract_hole_charts(screw_maker_file)
    cursor.executemany(
        "INSERT INTO fastener_hole_charts (chart_type, nominal_dia, hole_diameter) VALUES (?, ?, ?);",
        charts
    )

    # 5. Import Whole-Spec components (Transmission, Materials, Assembly Guides)
    ws_specs, ws_rows = import_whole_spec_components(cursor, whole_spec_db)

    conn.commit()
    conn.close()

    result = {
        "csv_files": len(csv_files),
        "tables": len(all_tables),
        "rows": len(data_rows) + ws_rows,
        "standards": len(std_rows) + ws_specs,
        "hole_charts": len(charts),
        "whole_spec_standards": ws_specs,
        "whole_spec_rows": ws_rows
    }

    print("Mechanical database import completed successfully:")
    print(f"  - Database: {output_db}")
    print(f"  - FreeCAD Standards:       {len(std_rows)}")
    print(f"  - Whole-Spec Standards:    {ws_specs}")
    print(f"  - Total Standards:         {result['standards']}")
    print(f"  - Total Data Rows:         {result['rows']:,}")
    print(f"  - Hole Chart Entries:      {result['hole_charts']}")

    return result


if __name__ == "__main__":
    t0 = time.time()
    import_fasteners()
    print(f"Done in {time.time() - t0:.2f}s")
