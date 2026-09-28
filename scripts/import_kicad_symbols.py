import argparse
import os
import re
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.common import (
    KICAD_SYMBOLS_DIR,
    DEFAULT_TARGET_DB,
    PartShelfImporter,
)

# Regex patterns to extract KiCad S-expression properties
RE_SYMBOL_NAME = re.compile(r'\(symbol\s+"([^"]+)"')
RE_VALUE_PROP = re.compile(r'\(property\s+"Value"\s+"([^"]*)"')
RE_FOOTPRINT_PROP = re.compile(r'\(property\s+"Footprint"\s+"([^"]*)"')
RE_DESC_PROP = re.compile(r'\(property\s+"Description"\s+"([^"]*)"')
RE_DATASHEET_PROP = re.compile(r'\(property\s+"Datasheet"\s+"([^"]*)"')
RE_FP_FILTERS = re.compile(r'\(property\s+"ki_fp_filters"\s+"([^"]*)"')


def infer_manufacturer_from_lib(lib_name: str, datasheet: str) -> str:
    """Infer common IC manufacturers from library name or datasheet URL."""
    name_upper = lib_name.upper()
    ds_lower = (datasheet or "").lower()

    if "STM32" in name_upper or "MCU_ST" in name_upper or "st.com" in ds_lower:
        return "STMicroelectronics"
    if "MICROCHIP" in name_upper or "ATMEGA" in name_upper or "ATTINY" in name_upper or "microchip.com" in ds_lower:
        return "Microchip Technology"
    if "TI" in name_upper or "TEXAS" in name_upper or "ti.com" in ds_lower:
        return "Texas Instruments"
    if "NXP" in name_upper or "nxp.com" in ds_lower:
        return "NXP Semiconductors"
    if "ESPRESSIF" in name_upper or "ESP32" in name_upper or "espressif.com" in ds_lower:
        return "Espressif Systems"
    if "WCH" in name_upper or "CH32" in name_upper or "wch-ic.com" in ds_lower:
        return "WCH"
    if "NORDIC" in name_upper or "nordicsemi.com" in ds_lower:
        return "Nordic Semiconductor"
    if "ON_SEMI" in name_upper or "onsemi.com" in ds_lower:
        return "ON Semiconductor"
    if "ANALOGDEVICES" in name_upper or "analog.com" in ds_lower:
        return "Analog Devices"
    if "INFINEON" in name_upper or "infineon.com" in ds_lower:
        return "Infineon Technologies"
    if "DIODES" in name_upper or "diodes.com" in ds_lower:
        return "Diodes Incorporated"
    if "ROHM" in name_upper or "rohm.com" in ds_lower:
        return "ROHM Semiconductor"

    # Default to library name clean form
    clean = lib_name.replace("MCU_", "").replace("Regulator_", "").replace("Sensor_", "").split("_")[0]
    return clean if clean else "Generic"


def clean_footprint_name(fp: str, fp_filter: str) -> str:
    """Extract clean package/footprint string."""
    clean = (fp or "").strip()
    if clean:
        if ":" in clean:
            clean = clean.split(":", 1)[1]
        return clean[:100]

    # Fallback to footprint filter pattern if given
    if fp_filter:
        clean_filt = fp_filter.split(" ")[0].replace("?", "").replace("*", "")
        if clean_filt:
            return clean_filt[:100]

    return "Symbol Generic"


def import_kicad_symbols(
    symbols_dir: Path,
    target_db_path: Path,
    limit: int = 1000,
    library_filter: str = None,
):
    if not symbols_dir.exists():
        raise FileNotFoundError(f"KiCad symbols directory not found at {symbols_dir}")

    print(f"[kicad-symbols] Scanning: {symbols_dir}")
    print(f"[kicad-symbols] Target database: {target_db_path}")
    print(f"[kicad-symbols] Limit: {limit if limit > 0 else 'All'}")

    # Discover all .kicad_symdir directories
    symdirs = sorted([p for p in symbols_dir.iterdir() if p.is_dir() and p.name.endswith(".kicad_symdir")])
    if library_filter:
        symdirs = [p for p in symdirs if library_filter.lower() in p.name.lower()]

    print(f"[kicad-symbols] Found {len(symdirs)} library directories to process.")

    importer = PartShelfImporter(target_db_path)
    start_time = time.time()
    total_processed = 0

    for sdir in symdirs:
        lib_name = sdir.name.replace(".kicad_symdir", "")
        sym_files = sorted(list(sdir.glob("*.kicad_sym")))

        for sym_file in sym_files:
            try:
                content = sym_file.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                continue

            # Extract fields
            val_match = RE_VALUE_PROP.search(content)
            sym_match = RE_SYMBOL_NAME.search(content)
            part_name = val_match.group(1).strip() if val_match else (sym_match.group(1).strip() if sym_match else sym_file.stem)

            # Skip virtual power symbols (#PWR, GND, VCC etc. unless desired)
            if part_name.startswith("#") or lib_name.lower() == "power":
                continue

            fp_match = RE_FOOTPRINT_PROP.search(content)
            footprint = fp_match.group(1).strip() if fp_match else ""

            fp_filt_match = RE_FP_FILTERS.search(content)
            fp_filter = fp_filt_match.group(1).strip() if fp_filt_match else ""

            desc_match = RE_DESC_PROP.search(content)
            description = desc_match.group(1).strip() if desc_match else ""

            ds_match = RE_DATASHEET_PROP.search(content)
            datasheet = ds_match.group(1).strip() if ds_match else ""
            if datasheet == "~":
                datasheet = ""

            package_type = clean_footprint_name(footprint, fp_filter)
            manufacturer = infer_manufacturer_from_lib(lib_name, datasheet)

            final_desc = description
            if datasheet:
                final_desc = f"{description} | Datasheet: {datasheet}" if description else f"Datasheet: {datasheet}"

            importer.add_part(
                name=part_name,
                description=final_desc,
                manufacturer=manufacturer,
                package=package_type,
                part_type=lib_name,
                quantity=0,
                disambiguate_suffix=f"KiCad_{lib_name}"
            )

            total_processed += 1
            if total_processed % 2000 == 0:
                importer.commit()
                print(f"[kicad-symbols] Processed {total_processed} files (Added: {importer.added_count}, Skipped: {importer.skipped_count})...")

            if limit > 0 and importer.added_count >= limit:
                break

        if limit > 0 and importer.added_count >= limit:
            break

    importer.close()
    elapsed = time.time() - start_time
    print(
        f"[kicad-symbols] Finished in {elapsed:.2f}s: Added {importer.added_count} parts, "
        f"Skipped {importer.skipped_count} duplicates/virtual symbols."
    )
    return importer.added_count, importer.skipped_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import electronic component symbols from KiCad libraries into PartShelf")
    parser.add_argument("--source", type=Path, default=KICAD_SYMBOLS_DIR, help="Path to kicad-symbols folder")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_DB, help="Path to target PartShelf database")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum number of parts to import (0 for all)")
    parser.add_argument("--library", type=str, default=None, help="Filter specific library name (e.g. MCU_ST_STM32)")

    args = parser.parse_args()
    import_kicad_symbols(
        symbols_dir=args.source,
        target_db_path=args.target,
        limit=args.limit,
        library_filter=args.library,
    )
