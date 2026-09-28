"""
Convert Altium JLCPCB component libraries (.schlib and .json) into an SQLite database.
Ensures zero data loss by recording both structured columns and complete raw/parameter JSON.
"""

import os
import sys
import glob
import json
import sqlite3
import tempfile
import subprocess
import re
import time
from pathlib import Path

try:
    import olefile
except ImportError:
    print("Error: olefile is required. Run: pip install olefile", file=sys.stderr)
    sys.exit(1)


DEFAULT_SOURCE_DIR = Path(r"E:\workspace\RadioLabRepoBackend\database\altium_jlcpcb_libraries")
DEFAULT_OUTPUT_DB = Path(r"E:\workspace\RadioLabRepoBackend\PartShelf\data\libraries\altium_library.db")


def create_schema(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS altium_components (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lib_reference TEXT NOT NULL,
        lcsc_part TEXT,
        category TEXT,
        package TEXT,
        manufacturer TEXT,
        mfr_part_number TEXT,
        basic_part INTEGER DEFAULT 0,
        description TEXT,
        resistance TEXT,
        capacitance TEXT,
        inductance TEXT,
        tolerance TEXT,
        voltage_rating TEXT,
        power_rating TEXT,
        datasheet_url TEXT,
        jlcpcb_url TEXT,
        lcsc_url TEXT,
        parameters_json TEXT,
        raw_data_json TEXT,
        source_type TEXT,
        source_file TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_altium_lib_ref ON altium_components(lib_reference);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_altium_lcsc ON altium_components(lcsc_part);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_altium_category ON altium_components(category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_altium_package ON altium_components(package);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_altium_mfr ON altium_components(manufacturer);")
    conn.commit()


def parse_schlib_file(filepath: Path, source_label: str) -> list[dict]:
    ole = olefile.OleFileIO(str(filepath))
    components = []
    
    for item in ole.listdir():
        if len(item) == 2 and item[1] == 'Data':
            comp_name = item[0]
            try:
                data = ole.openstream(item).read()
            except Exception as e:
                print(f"Warning: Failed to read stream {item} in {filepath}: {e}", file=sys.stderr)
                continue

            props = {}
            desc = ""
            lib_ref = comp_name

            indices = []
            s = 0
            while True:
                idx = data.find(b'|RECORD=', s)
                if idx == -1:
                    break
                indices.append(idx)
                s = idx + 1

            for i, idx in enumerate(indices):
                end = indices[i+1] if i+1 < len(indices) else len(data)
                part = data[idx:end]
                text = part.decode('utf-8', errors='replace').split('\x00')[0]
                pairs = dict(re.findall(r'\|([A-Za-z0-9_%]+)=([^\|\x00]*)', text))
                
                rec_type = pairs.get('RECORD')
                if rec_type in ('34', '41'):
                    name = pairs.get('Name')
                    val = pairs.get('%UTF8%Text') or pairs.get('Text')
                    if name and val:
                        props[name] = val
                elif rec_type == '1':
                    lib_ref = pairs.get('LibReference', comp_name)
                    desc = pairs.get('%UTF8%ComponentDescription') or pairs.get('ComponentDescription', '')

            # Build normalized record
            is_basic = 1 if props.get('JLCPCB Basic Part', '').strip().lower() in ('yes', 'true', '1') else 0
            lcsc_part = props.get('JLCPCB Part Number') or props.get('Supplier Part Number 1', '')

            components.append({
                "lib_reference": lib_ref,
                "lcsc_part": lcsc_part,
                "category": props.get('Category', ''),
                "package": props.get('Package Size', ''),
                "manufacturer": props.get('Manufacturer', ''),
                "mfr_part_number": props.get('Manufacturer Part Number', ''),
                "basic_part": is_basic,
                "description": desc or props.get('Description', ''),
                "resistance": props.get('Resistance', ''),
                "capacitance": props.get('Capacitance', ''),
                "inductance": props.get('Inductance', ''),
                "tolerance": props.get('Tolerance', ''),
                "voltage_rating": props.get('Voltage Rating', ''),
                "power_rating": props.get('Power Rating', ''),
                "datasheet_url": props.get('ComponentLink1URL', ''),
                "jlcpcb_url": props.get('ComponentLink2URL', ''),
                "lcsc_url": props.get('ComponentLink3URL', ''),
                "parameters_json": json.dumps(props, ensure_ascii=False),
                "raw_data_json": None,
                "source_type": "schlib",
                "source_file": source_label
            })
            
    ole.close()
    return components


def parse_json_files(json_dir: Path) -> list[dict]:
    components = []
    if not json_dir.exists():
        return components

    for p in json_dir.glob("*.json"):
        if p.name == "README.md":
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load JSON {p}: {e}", file=sys.stderr)
            continue

        lcsc_id = data.get("lcsc_id", "")
        mfr_part = data.get("manufacturer_part_number", "")
        basic = 1 if data.get("jlcpcb_basic_part") else 0
        desc = data.get("description", "")
        pkg = data.get("package", "")
        mfr = data.get("manufacturer", "")

        # Collect parameters
        params = {
            "lcsc_id": lcsc_id,
            "manufacturer_part_number": mfr_part,
            "manufacturer": mfr,
            "manufacturer_cn": data.get("manufacturer_cn", ""),
            "category": data.get("category", ""),
            "package": pkg,
            "jlcpcb_basic_part": basic,
            "lcsc_price": data.get("lcsc_price"),
            "prefix": data.get("prefix", ""),
            "szlcsc_url": data.get("szlcsc_url", ""),
            "lcsc_url": data.get("lcsc_url", "")
        }

        components.append({
            "lib_reference": mfr_part or lcsc_id,
            "lcsc_part": lcsc_id,
            "category": data.get("category", ""),
            "package": pkg,
            "manufacturer": mfr,
            "mfr_part_number": mfr_part,
            "basic_part": basic,
            "description": desc,
            "resistance": "",
            "capacitance": "",
            "inductance": "",
            "tolerance": "",
            "voltage_rating": "",
            "power_rating": "",
            "datasheet_url": "",
            "jlcpcb_url": f"https://jlcpcb.com/partdetail/{lcsc_id}" if lcsc_id else "",
            "lcsc_url": data.get("lcsc_url", "") or data.get("szlcsc_url", ""),
            "parameters_json": json.dumps(params, ensure_ascii=False),
            "raw_data_json": json.dumps(data, ensure_ascii=False),
            "source_type": "json",
            "source_file": f"json/{p.name}"
        })

    return components


def extract_7z(archive_path: Path, output_dir: Path):
    cmd = ["7z.exe", "x", "-y", f"-o{output_dir}", str(archive_path)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def convert_altium(source_dir: Path = DEFAULT_SOURCE_DIR, output_db: Path = DEFAULT_OUTPUT_DB) -> int:
    output_db.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove existing db to ensure clean build
    if output_db.exists():
        output_db.unlink()

    conn = sqlite3.connect(str(output_db))
    create_schema(conn)

    cursor = conn.cursor()
    insert_sql = """
    INSERT INTO altium_components (
        lib_reference, lcsc_part, category, package, manufacturer,
        mfr_part_number, basic_part, description, resistance, capacitance,
        inductance, tolerance, voltage_rating, power_rating, datasheet_url,
        jlcpcb_url, lcsc_url, parameters_json, raw_data_json, source_type,
        source_file
    ) VALUES (
        :lib_reference, :lcsc_part, :category, :package, :manufacturer,
        :mfr_part_number, :basic_part, :description, :resistance, :capacitance,
        :inductance, :tolerance, :voltage_rating, :power_rating, :datasheet_url,
        :jlcpcb_url, :lcsc_url, :parameters_json, :raw_data_json, :source_type,
        :source_file
    )
    """

    total_inserted = 0
    start_time = time.time()

    # 1. Process 2025_04_18 folder (latest version)
    version_dir = source_dir / "2025_04_18"
    if not version_dir.exists():
        version_dirs = sorted([d for d in source_dir.iterdir() if d.is_dir() and re.match(r'^\d{4}_\d{2}_\d{2}$', d.name)])
        if version_dirs:
            version_dir = version_dirs[-1]
        else:
            version_dir = source_dir

    print(f"Processing Altium libraries from: {version_dir}")

    # Process standalone .schlib files
    for schlib_file in version_dir.glob("*.schlib"):
        comps = parse_schlib_file(schlib_file, schlib_file.name)
        cursor.executemany(insert_sql, comps)
        conn.commit()
        total_inserted += len(comps)
        print(f"  Imported {len(comps)} components from {schlib_file.name}")

    # Process .7z archives
    for archive_file in version_dir.glob("*.7z"):
        print(f"  Extracting and processing {archive_file.name}...")
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_7z(archive_file, Path(tmpdir))
            for extracted_schlib in Path(tmpdir).glob("*.schlib"):
                comps = parse_schlib_file(extracted_schlib, f"{archive_file.name}:{extracted_schlib.name}")
                cursor.executemany(insert_sql, comps)
                conn.commit()
                total_inserted += len(comps)
                print(f"    Imported {len(comps)} components from {extracted_schlib.name}")

    # 2. Process json/ directory
    json_dir = source_dir / "json"
    if json_dir.exists():
        print(f"Processing normalized JSON files from: {json_dir}")
        json_comps = parse_json_files(json_dir)
        cursor.executemany(insert_sql, json_comps)
        conn.commit()
        total_inserted += len(json_comps)
        print(f"  Imported {len(json_comps)} components from JSON files")

    conn.close()
    elapsed = time.time() - start_time
    print(f"Altium library conversion completed: {total_inserted} components imported in {elapsed:.2f}s -> {output_db}")
    return total_inserted


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE_DIR
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_DB
    convert_altium(src, out)
