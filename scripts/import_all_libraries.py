"""
Master runner script to convert and import all three external component libraries
(Altium JLCPCB Libraries, KiCad Symbols, and JLCParts) into independent SQLite databases.
"""

import sys
import time
from pathlib import Path

# Add PartShelf root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.convert_altium import convert_altium, DEFAULT_SOURCE_DIR as ALTIUM_SRC, DEFAULT_OUTPUT_DB as ALTIUM_OUT
from scripts.convert_kicad import convert_kicad, DEFAULT_SOURCE_DIR as KICAD_SRC, DEFAULT_OUTPUT_DB as KICAD_OUT
from scripts.import_jlcparts import import_jlcparts, DEFAULT_SOURCE_DB as JLCPARTS_SRC, DEFAULT_OUTPUT_DB as JLCPARTS_OUT


def import_all():
    print("=" * 60)
    print("Starting conversion and import of all 3 external component libraries")
    print("=" * 60)
    total_start = time.time()

    # 1. Altium
    print("\n[1/3] Converting Altium JLCPCB Libraries...")
    altium_count = convert_altium(ALTIUM_SRC, ALTIUM_OUT)

    # 2. KiCad
    print("\n[2/3] Converting KiCad Symbol Libraries...")
    kicad_count = convert_kicad(KICAD_SRC, KICAD_OUT)

    # 3. JLCParts
    print("\n[3/3] Importing JLCParts Component Database...")
    jlcparts_count = import_jlcparts(JLCPARTS_SRC, JLCPARTS_OUT)

    total_time = time.time() - total_start
    print("\n" + "=" * 60)
    print(f"All 3 libraries imported successfully in {total_time:.2f} seconds!")
    print(f"  1. Altium Library:   {altium_count:,} components -> {ALTIUM_OUT}")
    print(f"  2. KiCad Symbols:    {kicad_count:,} symbols    -> {KICAD_OUT}")
    print(f"  3. JLCParts Database:{jlcparts_count:,} parts      -> {JLCPARTS_OUT}")
    print("=" * 60)


if __name__ == "__main__":
    import_all()
