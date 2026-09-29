"""
BOM (Bill of Materials) Parsing and Import Service for PartShelf.
Supports .xlsx and .csv files exported from EasyEDA (嘉立创EDA) and generic EDA tools.
Provides column normalization, multi-library matching, zero-stock part generation,
custom component creation, and project BOM linking.
"""

import io
import re
import csv
import openpyxl
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_part import ProjectPart
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.custom_component import CustomComponent
from app.services import external_library_service as lib_svc


HEADER_ALIASES = {
    "supplier_part": [
        "supplier part", "supplierpart", "lcsc part", "lcsc part #", "lcsc",
        "立创编号", "客户编号", "器件编号", "料号", "立创料号", "supplier_part"
    ],
    "quantity": [
        "quantity", "qty", "数量", "用量", "单板用量", "count", "num"
    ],
    "designator": [
        "designator", "ref", "reference", "refdes", "位号", "参考编号", "元件位置"
    ],
    "footprint": [
        "footprint", "package", "封装", "规格封装", "封装规格"
    ],
    "comment": [
        "comment", "value", "型号", "规格", "参数", "器件型号", "值", "元件型号", "description"
    ],
    "manufacturer_part": [
        "manufacturer part", "mfr.part #", "mfr part", "mfr part #", "mpn",
        "厂商型号", "厂家型号", "厂家料号", "品牌型号", "manufacturer_part"
    ],
    "manufacturer": [
        "manufacturer", "mfr", "brand", "厂商", "品牌", "生产厂家"
    ],
}


def normalize_header(header: str) -> Optional[str]:
    """Matches raw header string against canonical aliases."""
    if not header:
        return None
    h = str(header).strip().lower()
    # 1. Exact match first across all canonical keys and aliases
    for canon, aliases in HEADER_ALIASES.items():
        if h == canon or h in aliases:
            return canon

    # 2. Specific substring matches (order matters: specific keys before generic ones)
    ordered_keys = [
        "manufacturer_part", "supplier_part", "designator",
        "footprint", "manufacturer", "quantity", "comment"
    ]
    for canon in ordered_keys:
        for alias in HEADER_ALIASES[canon]:
            if alias in h:
                return canon
    return None


def extract_c_code(val: Any) -> Optional[int]:
    """Extracts integer LCSC number from string like 'C318941', 'c1576', 'C6119763'."""
    if val is None:
        return None
    s = str(val).strip()
    match = re.search(r'\b[Cc]([0-9]{3,10})\b', s)
    if match:
        return int(match.group(1))
    if s.isdigit() and len(s) >= 3 and len(s) <= 10:
        return int(s)
    return None


def parse_bom_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """
    Parses an uploaded BOM file (.xlsx, .xls, or .csv) and returns a list of row dicts
    containing canonical keys: supplier_part, quantity, designator, footprint, comment,
    manufacturer_part, manufacturer, and raw_row.
    """
    fn = filename.lower()
    rows = []

    if fn.endswith((".xlsx", ".xls")):
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active
        raw_rows = list(sheet.iter_rows(values_only=True))
        if not raw_rows:
            return []

        header_row = raw_rows[0]
        col_map: Dict[int, str] = {}
        for idx, col in enumerate(header_row):
            canon = normalize_header(col)
            if canon and canon not in col_map.values():
                col_map[idx] = canon

        for row_idx, r in enumerate(raw_rows[1:], start=2):
            if not r or all(cell is None or str(cell).strip() == "" for cell in r):
                continue
            row_dict: Dict[str, Any] = {
                "supplier_part": None,
                "quantity": 1,
                "designator": "",
                "footprint": "",
                "comment": "",
                "manufacturer_part": "",
                "manufacturer": "",
                "raw_row": [str(c) if c is not None else "" for c in r]
            }
            for idx, canon in col_map.items():
                if idx < len(r):
                    val = r[idx]
                    if val is not None:
                        row_dict[canon] = str(val).strip()

            # Clean quantity
            try:
                q = int(float(row_dict["quantity"]))
                row_dict["quantity"] = max(1, q)
            except (ValueError, TypeError):
                row_dict["quantity"] = 1

            rows.append(row_dict)

    else:
        # CSV parsing with encoding fallback
        text_content = None
        for enc in ["utf-8-sig", "utf-8", "gb18030", "gbk"]:
            try:
                text_content = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if text_content is None:
            text_content = file_bytes.decode("utf-8", errors="replace")

        reader = csv.reader(io.StringIO(text_content))
        raw_rows = list(reader)
        if not raw_rows:
            return []

        header_row = raw_rows[0]
        col_map = {}
        for idx, col in enumerate(header_row):
            canon = normalize_header(col)
            if canon and canon not in col_map.values():
                col_map[idx] = canon

        for row_idx, r in enumerate(raw_rows[1:], start=2):
            if not r or all(str(cell).strip() == "" for cell in r):
                continue
            row_dict = {
                "supplier_part": None,
                "quantity": 1,
                "designator": "",
                "footprint": "",
                "comment": "",
                "manufacturer_part": "",
                "manufacturer": "",
                "raw_row": r
            }
            for idx, canon in col_map.items():
                if idx < len(r):
                    val = r[idx]
                    if val is not None:
                        row_dict[canon] = str(val).strip()

            try:
                q = int(float(row_dict["quantity"]))
                row_dict["quantity"] = max(1, q)
            except (ValueError, TypeError):
                row_dict["quantity"] = 1

            rows.append(row_dict)

    return rows


def analyze_bom_matching(parsed_rows: List[Dict[str, Any]], db: Session, lang: str = "zh") -> Dict[str, Any]:
    """
    Analyzes each row of the parsed BOM and matches against:
    1. Local inventory (Part table)
    2. JLCParts library (jlcparts.db)
    3. Altium library (altium_library.db)
    Returns preview items with match statuses: 'in_inventory', 'matched_library', 'unmatched'.
    """
    preview_items = []
    in_inv_count = 0
    matched_lib_count = 0
    unmatched_count = 0

    for idx, row in enumerate(parsed_rows, start=1):
        item = {
            "row_index": idx,
            "quantity": row.get("quantity", 1),
            "designator": row.get("designator", ""),
            "footprint": row.get("footprint", ""),
            "comment": row.get("comment", ""),
            "manufacturer_part": row.get("manufacturer_part", ""),
            "manufacturer": row.get("manufacturer", ""),
            "raw_supplier_part": row.get("supplier_part", ""),
            "status": "unmatched",
            "library_source": None,
            "external_part_id": None,
            "matched_part_name": None,
            "matched_manufacturer": None,
            "matched_package": None,
            "matched_stock": None,
            "inventory_part_id": None,
            "inventory_quantity": 0,
            "auto_create_zero_stock": True,
            "selected": True,
        }

        # Check LCSC C-code first
        lcsc_num = extract_c_code(row.get("supplier_part"))
        if not lcsc_num:
            # Fallback: check if comment or manufacturer_part contains C-code
            lcsc_num = extract_c_code(row.get("comment")) or extract_c_code(row.get("manufacturer_part"))

        if lcsc_num:
            # 1. Check local inventory for this JLCParts component
            inv_part = db.query(Part).filter(
                Part.library_source == "jlcparts",
                Part.external_part_id == str(lcsc_num)
            ).first()

            if inv_part:
                summary = lib_svc.resolve_part_summary("jlcparts", str(lcsc_num), lang=lang)
                item["status"] = "in_inventory"
                item["library_source"] = "jlcparts"
                item["external_part_id"] = str(lcsc_num)
                item["matched_part_name"] = summary.get("name") or f"C{lcsc_num}"
                item["matched_manufacturer"] = summary.get("manufacturer")
                item["matched_package"] = summary.get("package")
                item["inventory_part_id"] = inv_part.id
                item["inventory_quantity"] = inv_part.inventory.quantity_available if inv_part.inventory else 0
                item["auto_create_zero_stock"] = False
                in_inv_count += 1
                preview_items.append(item)
                continue

            # 2. Check JLCParts library
            jlc_comp = lib_svc.get_jlcparts_component(lcsc_num, lang=lang)
            if jlc_comp:
                item["status"] = "matched_library"
                item["library_source"] = "jlcparts"
                item["external_part_id"] = str(lcsc_num)
                item["matched_part_name"] = jlc_comp.get("mfr") or f"C{lcsc_num}"
                item["matched_manufacturer"] = jlc_comp.get("manufacturer")
                item["matched_package"] = jlc_comp.get("package")
                item["matched_stock"] = jlc_comp.get("stock", 0)
                item["auto_create_zero_stock"] = True
                matched_lib_count += 1
                preview_items.append(item)
                continue

        # If no C-code or JLCParts match, try searching Altium library by manufacturer_part or comment
        search_kw = (row.get("manufacturer_part") or "").strip()
        if not search_kw and row.get("comment"):
            # Avoid searching generic short terms like '0.1uF' or 'SMT'
            cand = row.get("comment").strip()
            if len(cand) >= 4 and not re.match(r'^[0-9.]+[uUpPnN]?[fF]?$', cand):
                search_kw = cand

        if search_kw:
            # Check local inventory first
            inv_part = db.query(Part).filter(
                Part.library_source == "altium",
                Part.external_part_id == search_kw
            ).first()
            if inv_part:
                summary = lib_svc.resolve_part_summary("altium", search_kw, lang=lang)
                item["status"] = "in_inventory"
                item["library_source"] = "altium"
                item["external_part_id"] = search_kw
                item["matched_part_name"] = summary.get("name")
                item["matched_manufacturer"] = summary.get("manufacturer")
                item["matched_package"] = summary.get("package")
                item["inventory_part_id"] = inv_part.id
                item["inventory_quantity"] = inv_part.inventory.quantity_available if inv_part.inventory else 0
                item["auto_create_zero_stock"] = False
                in_inv_count += 1
                preview_items.append(item)
                continue

            altium_search = lib_svc.search_altium(search_kw, page_size=1, lang=lang)
            if altium_search.get("items"):
                top_match = altium_search["items"][0]
                item["status"] = "matched_library"
                item["library_source"] = "altium"
                item["external_part_id"] = str(top_match["id"])
                item["matched_part_name"] = top_match.get("lib_reference") or top_match.get("mfr_part_number")
                item["matched_manufacturer"] = top_match.get("manufacturer")
                item["matched_package"] = top_match.get("package")
                item["auto_create_zero_stock"] = True
                matched_lib_count += 1
                preview_items.append(item)
                continue

        # If not matched
        item["status"] = "unmatched"
        unmatched_count += 1
        preview_items.append(item)

    return {
        "total_rows": len(parsed_rows),
        "in_inventory_count": in_inv_count,
        "matched_library_count": matched_lib_count,
        "unmatched_count": unmatched_count,
        "items": preview_items,
    }


def execute_bom_import(
    db: Session,
    target_type: str,
    project_name: Optional[str],
    project_description: Optional[str],
    existing_project_id: Optional[int],
    quantity_strategy: str,
    items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Executes the confirmed BOM import.
    - Creates or retrieves target Project.
    - Creates zero-stock Part records for library-matched components if requested.
    - Creates CustomComponent and Part records for custom components.
    - Connects parts to ProjectPart with selected merge strategy ('overwrite' or 'add').
    """
    # 1. Target Project resolution
    if target_type == "new":
        name = (project_name or "").strip()
        if not name:
            name = "New BOM Project"
        project = Project(
            name=name,
            description=(project_description or "").strip() if project_description else None
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    else:
        if not existing_project_id:
            raise ValueError("existing_project_id is required when target_type is 'existing'")
        project = db.query(Project).filter(Project.id == existing_project_id).first()
        if not project:
            raise ValueError(f"Project with ID {existing_project_id} not found")

    imported_count = 0
    created_parts_count = 0

    # 2. Iterate confirmed items
    for item in items:
        if not item.get("selected", True):
            continue

        part_id = item.get("inventory_part_id")
        qty_needed = max(1, int(item.get("quantity", 1)))
        lib_src = item.get("library_source")
        ext_id = str(item.get("external_part_id") or "").strip()

        # If item needs a new Part record (e.g. matched library or custom)
        if not part_id:
            if item.get("is_custom") or lib_src == "custom":
                custom_name = item.get("custom_name") or item.get("comment") or "Custom Part"
                custom_mfr = item.get("custom_manufacturer") or item.get("manufacturer") or "Generic"
                custom_pkg = item.get("custom_package") or item.get("footprint") or "Standard"
                custom_desc = item.get("custom_description") or f"Imported for project #{project.id}"

                custom_comp = CustomComponent(
                    name=custom_name,
                    manufacturer=custom_mfr,
                    package=custom_pkg,
                    part_type="Custom",
                    description=custom_desc
                )
                db.add(custom_comp)
                db.commit()
                db.refresh(custom_comp)

                new_part = Part(
                    library_source="custom",
                    external_part_id=str(custom_comp.id),
                    storage_location="Default Storage",
                    note=f"Custom BOM Part for {project.name}"
                )
                db.add(new_part)
                db.commit()
                db.refresh(new_part)

                new_inv = Inventory(part_id=new_part.id, quantity_available=0)
                db.add(new_inv)
                db.commit()

                part_id = new_part.id
                created_parts_count += 1

            elif lib_src in ("jlcparts", "altium", "kicad") and ext_id:
                if not item.get("auto_create_zero_stock", True):
                    continue

                # Check again if part was created in an earlier row in this same batch
                existing_part = db.query(Part).filter(
                    Part.library_source == lib_src,
                    Part.external_part_id == ext_id
                ).first()

                if existing_part:
                    part_id = existing_part.id
                else:
                    new_part = Part(
                        library_source=lib_src,
                        external_part_id=ext_id,
                        storage_location="Default Storage",
                        note=f"Auto-created from BOM import for {project.name}"
                    )
                    db.add(new_part)
                    db.commit()
                    db.refresh(new_part)

                    new_inv = Inventory(part_id=new_part.id, quantity_available=0)
                    db.add(new_inv)
                    db.commit()

                    part_id = new_part.id
                    created_parts_count += 1

        if not part_id:
            # Unmatched row without resolution, skip
            continue

        # 3. Associate with ProjectPart
        existing_pp = db.query(ProjectPart).filter(
            ProjectPart.project_id == project.id,
            ProjectPart.part_id == part_id
        ).first()

        if existing_pp:
            if quantity_strategy == "add":
                existing_pp.quantity_needed = (existing_pp.quantity_needed or 0) + qty_needed
            else:
                # 'overwrite' strategy
                existing_pp.quantity_needed = qty_needed
        else:
            new_pp = ProjectPart(
                project_id=project.id,
                part_id=part_id,
                quantity_needed=qty_needed
            )
            db.add(new_pp)

        imported_count += 1

    db.commit()

    return {
        "success": True,
        "project_id": project.id,
        "project_name": project.name,
        "imported_parts_count": imported_count,
        "created_inventory_parts_count": created_parts_count,
    }
