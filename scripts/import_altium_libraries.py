import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.common import (
    ALTIUM_DIR,
    DEFAULT_TARGET_DB,
    PartShelfImporter,
)


def extract_category_from_url(url: str) -> str:
    """Extract human-readable component category from LCSC URL slug."""
    if not url:
        return "Passive"
    try:
        parts = url.split("/product-detail/")
        if len(parts) > 1:
            slug = parts[1].split("_")[0]
            return slug.replace("-", " ")
    except Exception:
        pass
    return "Electronic Component"


def import_altium_libraries(
    altium_dir: Path,
    target_db_path: Path,
    limit: int = 1000,
):
    json_dir = altium_dir / "json"
    if not json_dir.exists():
        raise FileNotFoundError(f"Altium JSON directory not found at {json_dir}")

    print(f"[altium_jlcpcb_libraries] Scanning: {json_dir}")
    print(f"[altium_jlcpcb_libraries] Target database: {target_db_path}")
    print(f"[altium_jlcpcb_libraries] Limit: {limit if limit > 0 else 'All'}")

    json_files = sorted(list(json_dir.glob("*.json")))
    print(f"[altium_jlcpcb_libraries] Found {len(json_files)} JSON component files to process.")

    importer = PartShelfImporter(target_db_path)
    start_time = time.time()

    for idx, jf in enumerate(json_files, 1):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            continue

        lcsc_id = data.get("lcsc_id", "")
        mpn = data.get("manufacturer_part_number") or data.get("lcsc_part_name") or f"C{lcsc_id}"
        mfr = data.get("manufacturer") or data.get("manufacturer_cn") or "Generic"
        pkg = data.get("package") or "SMD"

        # Determine category / type
        category = extract_category_from_url(data.get("lcsc_url", ""))

        # Assemble clean description
        desc_parts = []
        raw_desc = (data.get("description") or "").strip()
        if raw_desc:
            desc_parts.append(raw_desc)
        if data.get("jlcpcb_basic_part"):
            desc_parts.append("JLCPCB Basic Part")
        price = data.get("lcsc_price")
        if price:
            desc_parts.append(f"Price: ${price}")
        img_url = data.get("szlcsc_image")
        if img_url:
            desc_parts.append(f"Image: {img_url}")

        description = " | ".join(desc_parts) if desc_parts else f"LCSC C{lcsc_id}"

        importer.add_part(
            name=mpn,
            description=description,
            manufacturer=mfr,
            package=pkg,
            part_type=category,
            quantity=0,
            disambiguate_suffix=f"C{lcsc_id}" if lcsc_id else "Altium"
        )

        if idx % 500 == 0:
            importer.commit()
            print(f"[altium_jlcpcb_libraries] Processed {idx}/{len(json_files)} files (Added: {importer.added_count}, Skipped: {importer.skipped_count})...")

        if limit > 0 and importer.added_count >= limit:
            break

    importer.close()
    elapsed = time.time() - start_time
    print(
        f"[altium_jlcpcb_libraries] Finished in {elapsed:.2f}s: Added {importer.added_count} parts, "
        f"Skipped {importer.skipped_count} duplicates/empty."
    )
    return importer.added_count, importer.skipped_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import electronic components from altium_jlcpcb_libraries into PartShelf")
    parser.add_argument("--source", type=Path, default=ALTIUM_DIR, help="Path to altium_jlcpcb_libraries folder")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_DB, help="Path to target PartShelf database")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum number of parts to import (0 for all)")

    args = parser.parse_args()
    import_altium_libraries(
        altium_dir=args.source,
        target_db_path=args.target,
        limit=args.limit,
    )
