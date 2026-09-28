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
    KICAD_SYMBOLS_DIR,
    ALTIUM_DIR,
    DEFAULT_TARGET_DB,
)
from scripts.import_jlcparts import import_jlcparts
from scripts.import_kicad_symbols import import_kicad_symbols
from scripts.import_altium_libraries import import_altium_libraries


def get_db_stats(db_path: Path):
    if not db_path.exists():
        return 0, 0, 0, 0
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM parts")
    parts_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM manufacturers")
    mfr_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM packages")
    pkg_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM types")
    type_count = cur.fetchone()[0]
    conn.close()
    return parts_count, mfr_count, pkg_count, type_count


def run_all_imports(
    target_db: Path = DEFAULT_TARGET_DB,
    jlc_limit: int = 500,
    kicad_limit: int = 500,
    altium_limit: int = 500,
    skip_jlc: bool = False,
    skip_kicad: bool = False,
    skip_altium: bool = False,
):
    print("=" * 60)
    print("PartShelf Unified Multi-Source Component Importer")
    print(f"Target SQLite Database: {target_db}")
    print("=" * 60)

    p_init, m_init, pkg_init, t_init = get_db_stats(target_db)
    print(f"Initial State: {p_init} Parts | {m_init} Manufacturers | {pkg_init} Packages | {t_init} Types\n")

    results = {}
    overall_start = time.time()

    # 1. JLCParts
    if not skip_jlc:
        print("\n--- [1/3] Importing from jlcparts ---")
        try:
            added, skipped = import_jlcparts(
                source_db_path=JLCPARTS_DB_PRIMARY,
                target_db_path=target_db,
                limit=jlc_limit,
                include_chips_priority=True,
            )
            results["jlcparts"] = {"status": "Success", "added": added, "skipped": skipped}
        except Exception as e:
            print(f"Error importing from jlcparts: {e}")
            results["jlcparts"] = {"status": f"Failed: {e}", "added": 0, "skipped": 0}
    else:
        results["jlcparts"] = {"status": "Skipped", "added": 0, "skipped": 0}

    # 2. KiCad Symbols
    if not skip_kicad:
        print("\n--- [2/3] Importing from kicad-symbols ---")
        try:
            added, skipped = import_kicad_symbols(
                symbols_dir=KICAD_SYMBOLS_DIR,
                target_db_path=target_db,
                limit=kicad_limit,
            )
            results["kicad-symbols"] = {"status": "Success", "added": added, "skipped": skipped}
        except Exception as e:
            print(f"Error importing from kicad-symbols: {e}")
            results["kicad-symbols"] = {"status": f"Failed: {e}", "added": 0, "skipped": 0}
    else:
        results["kicad-symbols"] = {"status": "Skipped", "added": 0, "skipped": 0}

    # 3. Altium Libraries
    if not skip_altium:
        print("\n--- [3/3] Importing from altium_jlcpcb_libraries ---")
        try:
            added, skipped = import_altium_libraries(
                altium_dir=ALTIUM_DIR,
                target_db_path=target_db,
                limit=altium_limit,
            )
            results["altium_jlcpcb_libraries"] = {"status": "Success", "added": added, "skipped": skipped}
        except Exception as e:
            print(f"Error importing from altium_jlcpcb_libraries: {e}")
            results["altium_jlcpcb_libraries"] = {"status": f"Failed: {e}", "added": 0, "skipped": 0}
    else:
        results["altium_jlcpcb_libraries"] = {"status": "Skipped", "added": 0, "skipped": 0}

    overall_elapsed = time.time() - overall_start
    p_final, m_final, pkg_final, t_final = get_db_stats(target_db)

    print("\n" + "=" * 60)
    print("Import Execution Summary")
    print("=" * 60)
    for source, data in results.items():
        print(f"  {source:28}: {data['status']} (+{data['added']} added, {data['skipped']} skipped)")

    print("-" * 60)
    print(f"Total time elapsed   : {overall_elapsed:.2f} seconds")
    print(f"Parts count delta    : {p_init} -> {p_final} (+{p_final - p_init})")
    print(f"Manufacturers delta  : {m_init} -> {m_final} (+{m_final - m_init})")
    print(f"Packages delta       : {pkg_init} -> {pkg_final} (+{pkg_final - pkg_init})")
    print(f"Types/Categories delta: {t_init} -> {t_final} (+{t_final - t_init})")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Master importer: Convert and load components into PartShelf SQLite DB")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_DB, help="Path to PartShelf SQLite database")
    parser.add_argument("--all", action="store_true", help="Import all available components without limit")
    parser.add_argument("--jlcparts-limit", type=int, default=500, help="Limit for jlcparts (default: 500)")
    parser.add_argument("--kicad-limit", type=int, default=500, help="Limit for kicad-symbols (default: 500)")
    parser.add_argument("--altium-limit", type=int, default=500, help="Limit for altium (default: 500)")
    parser.add_argument("--skip-jlc", action="store_true", help="Skip jlcparts")
    parser.add_argument("--skip-kicad", action="store_true", help="Skip kicad-symbols")
    parser.add_argument("--skip-altium", action="store_true", help="Skip altium_jlcpcb_libraries")

    args = parser.parse_args()

    jlc_lim = 0 if args.all else args.jlcparts_limit
    kicad_lim = 0 if args.all else args.kicad_limit
    altium_lim = 0 if args.all else args.altium_limit

    run_all_imports(
        target_db=args.target,
        jlc_limit=jlc_lim,
        kicad_limit=kicad_lim,
        altium_limit=altium_lim,
        skip_jlc=args.skip_jlc,
        skip_kicad=args.skip_kicad,
        skip_altium=args.skip_altium,
    )
