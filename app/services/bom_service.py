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
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_part import ProjectPart
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.custom_component import CustomComponent
from app.services.bom_matcher import BomMatcher, candidate_conflicts, component_kind, normalized_code, public_candidate, row_conflicts


HEADER_ALIASES = {
    "value": ["value", "元件值", "标称值"],
    "primary_category": ["primary category", "一级分类"],
    "secondary_category": ["secondary category", "二级分类"],
    "pin_count": ["pin count", "pins", "引脚数"],
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
        "comment", "型号", "规格", "参数", "器件型号", "值", "元件型号", "description"
    ],
    "manufacturer_part": [
        "manufacturer part", "mfr.part #", "mfr part", "mfr part #", "mpn",
        "厂商型号", "厂家型号", "厂家料号", "品牌型号", "manufacturer_part"
    ],
    "manufacturer": [
        "manufacturer", "mfr", "brand", "厂商", "品牌", "生产厂家"
    ],
    "mechanical_standard": ["standard", "standard code", "标准", "标准号", "执行标准"],
    "mechanical_nominal": ["nominal size", "nominal", "thread size", "公称尺寸", "螺纹规格"],
    "mechanical_length": ["length", "screw length", "bolt length", "长度", "螺杆长度"],
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
        "mechanical_standard", "mechanical_nominal", "mechanical_length",
        "manufacturer_part", "supplier_part", "primary_category", "secondary_category",
        "pin_count", "designator", "footprint", "manufacturer", "quantity", "value", "comment"
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
    containing canonical keys including independent value, category and pin count fields.
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
                "value": "",
                "primary_category": "",
                "secondary_category": "",
                "pin_count": "",
                "manufacturer_part": "",
                "manufacturer": "",
                "mechanical_standard": "",
                "mechanical_nominal": "",
                "mechanical_length": "",
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
                "value": "",
                "primary_category": "",
                "secondary_category": "",
                "pin_count": "",
                "manufacturer_part": "",
                "manufacturer": "",
                "mechanical_standard": "",
                "mechanical_nominal": "",
                "mechanical_length": "",
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
    """Preview exact supplier codes and review-only substitute candidates."""
    preview_items = []
    matcher = BomMatcher()
    try:
        for idx, row in enumerate(parsed_rows, start=1):
            kind = component_kind(row)
            internal_conflicts = row_conflicts(row, kind)
            item = {
                "row_index": idx,
                "quantity": row.get("quantity", 1),
                "designator": row.get("designator", ""),
                "footprint": row.get("footprint", ""),
                "comment": row.get("comment", ""),
                "value": row.get("value", ""),
                "primary_category": row.get("primary_category", ""),
                "secondary_category": row.get("secondary_category", ""),
                "pin_count": row.get("pin_count", ""),
                "manufacturer_part": row.get("manufacturer_part", ""),
                "manufacturer": row.get("manufacturer", ""),
                "mechanical_standard": row.get("mechanical_standard", ""),
                "mechanical_nominal": row.get("mechanical_nominal", ""),
                "mechanical_length": row.get("mechanical_length", ""),
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
                "selected": False,
                "confirmed_match": False,
                "match_reason": "",
                "missing_dimensions": [],
                "conflicts": internal_conflicts.copy(),
                "suggestions": [],
            }
            if kind == "fastener":
                match = matcher.fastener_match(row)
                item["match_reason"] = match["reason"]
                item["missing_dimensions"] = match["missing_dimensions"]
                if len(match["items"]) == 1:
                    candidate = match["items"][0]
                    inv_part = db.query(Part).filter(
                        Part.library_source == "fasteners",
                        Part.external_part_id == candidate["external_part_id"],
                    ).first()
                    item.update(
                        status="in_inventory" if inv_part else "matched_library",
                        library_source="fasteners",
                        external_part_id=candidate["external_part_id"],
                        matched_part_name=candidate["name"],
                        matched_manufacturer=candidate["authority"],
                        matched_package=candidate["package"],
                        matched_stock=0,
                        inventory_part_id=inv_part.id if inv_part else None,
                        inventory_quantity=(inv_part.inventory.quantity_available if inv_part and inv_part.inventory else 0),
                        auto_create_zero_stock=not bool(inv_part),
                        selected=True,
                    )
                else:
                    item["suggestions"] = match["items"]
                preview_items.append(item)
                continue

            code = (extract_c_code(row.get("supplier_part"))
                    or extract_c_code(row.get("manufacturer_part"))
                    or extract_c_code(row.get("comment")))
            exact = matcher.exact_code(str(code)) if code else []
            stale_inventory = None
            if code and not exact:
                stale_inventory = db.query(Part).filter(
                    Part.library_source == "jlcparts",
                    Part.external_part_id == str(code),
                ).first()
            exact_ranked = sorted(exact, key=lambda candidate: (
                bool(candidate_conflicts(row, candidate, kind)),
                0 if candidate["library_source"] == "jlcparts" else 1,
                candidate["external_part_id"],
            ))
            valid_exact = [candidate for candidate in exact_ranked
                           if not candidate_conflicts(row, candidate, kind)]
            if valid_exact and not internal_conflicts:
                candidate = valid_exact[0]
                inv_part = db.query(Part).filter(
                    Part.library_source == candidate["library_source"],
                    Part.external_part_id == candidate["external_part_id"],
                ).first()
                item.update(
                    status="in_inventory" if inv_part else "matched_library",
                    library_source=candidate["library_source"],
                    external_part_id=candidate["external_part_id"],
                    matched_part_name=candidate["name"],
                    matched_manufacturer=candidate.get("manufacturer"),
                    matched_package=candidate.get("package"),
                    matched_stock=candidate.get("stock", 0),
                    inventory_part_id=inv_part.id if inv_part else None,
                    inventory_quantity=(inv_part.inventory.quantity_available if inv_part and inv_part.inventory else 0),
                    auto_create_zero_stock=not bool(inv_part),
                    selected=True,
                    match_reason="exact_supplier_code",
                )
            else:
                item["match_reason"] = "conflict" if exact or internal_conflicts else (
                    "original_code_missing" if code else "no_supplier_code")
                model_matches = matcher.exact_model(row.get("manufacturer_part") or "")
                if model_matches and all(candidate_conflicts(row, candidate, kind) for candidate in model_matches):
                    for model_candidate in model_matches:
                        item["conflicts"] = list(dict.fromkeys(
                            item["conflicts"] + candidate_conflicts(row, model_candidate, kind)))
                    item["match_reason"] = "conflict"
                for candidate in exact_ranked:
                    conflicts = candidate_conflicts(row, candidate, kind)
                    item["conflicts"] = list(dict.fromkeys(item["conflicts"] + conflicts))
                    item["suggestions"].append(public_candidate(candidate, "exact_supplier_code", conflicts))
                if stale_inventory:
                    item["match_reason"] = "inventory_reference_missing"
                    item["conflicts"].append("missing_reference")
                    item["suggestions"].insert(0, public_candidate({
                        "library_source": "jlcparts", "external_part_id": str(code),
                        "lcsc": code, "name": f"C{code}", "package": "",
                        "stock": (stale_inventory.inventory.quantity_available if stale_inventory.inventory else 0),
                    }, "inventory_reference", ["missing_reference"]))
                excluded = {(candidate["library_source"], candidate["external_part_id"]) for candidate in exact}
                remaining = 10 - len(item["suggestions"])
                if remaining > 0:
                    item["suggestions"].extend(matcher.suggestions(row, kind, excluded)[:remaining])
                item["suggestions"] = item["suggestions"][:10]
            preview_items.append(item)
    finally:
        matcher.close()
    return {
        "total_rows": len(parsed_rows),
        "in_inventory_count": sum(item["status"] == "in_inventory" for item in preview_items),
        "matched_library_count": sum(item["status"] == "matched_library" for item in preview_items),
        "unmatched_count": sum(item["status"] == "unmatched" for item in preview_items),
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
    # Validate all proposed links before creating a project or inventory record.
    matcher = BomMatcher()
    try:
        for item in items:
            if not item.get("selected", True) or item.get("is_custom"):
                continue
            source = item.get("library_source")
            external_id = str(item.get("external_part_id") or "").strip()
            if source == "fasteners" and external_id:
                row = {
                    "value": item.get("value"), "comment": item.get("comment"),
                    "footprint": item.get("footprint"), "manufacturer_part": item.get("manufacturer_part"),
                    "primary_category": item.get("primary_category"),
                    "secondary_category": item.get("secondary_category"),
                    "designator": item.get("designator"),
                    "mechanical_standard": item.get("mechanical_standard"),
                    "mechanical_nominal": item.get("mechanical_nominal"),
                    "mechanical_length": item.get("mechanical_length"),
                }
                match = matcher.fastener_match(row)
                if not matcher.validate_fastener_match(row, external_id):
                    raise ValueError(f"Row {item.get('row_index')}: fastener dimensions do not match the selected standard variant")
                if len(match["items"]) != 1 and not item.get("confirmed_match", False):
                    raise ValueError(f"Row {item.get('row_index')}: manual confirmation is required for this fastener match")
                continue
            if source == "kicad" and external_id:
                if not item.get("confirmed_match", False):
                    raise ValueError(f"Row {item.get('row_index')}: manual confirmation is required for this library match")
                continue
            if source not in ("jlcparts", "altium") or not external_id:
                continue
            candidate = matcher.lookup(source, external_id)
            supplied_code = (extract_c_code(item.get("raw_supplier_part"))
                             or extract_c_code(item.get("manufacturer_part"))
                             or extract_c_code(item.get("comment")))
            candidate_code = normalized_code(candidate.get("lcsc_part") if source == "altium" else candidate.get("lcsc")) if candidate else None
            exact_code = supplied_code is not None and candidate_code == str(supplied_code)
            row = {
                "value": item.get("value"), "comment": item.get("comment"),
                "footprint": item.get("footprint"), "pin_count": item.get("pin_count"),
                "designator": item.get("designator"),
                "primary_category": item.get("primary_category"),
                "secondary_category": item.get("secondary_category"),
            }
            kind = component_kind(row)
            conflicts = row_conflicts(row, kind)
            if candidate:
                conflicts.extend(candidate_conflicts(row, candidate, kind))
            if (not exact_code or conflicts) and not item.get("confirmed_match", False):
                raise ValueError(f"Row {item.get('row_index')}: manual confirmation is required for this library match")
    finally:
        matcher.close()

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
    skipped_unresolved_count = 0

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

            elif lib_src in ("jlcparts", "altium", "kicad", "fasteners") and ext_id:
                if not item.get("auto_create_zero_stock", True):
                    skipped_unresolved_count += 1
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
            skipped_unresolved_count += 1
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
        "skipped_unresolved_count": skipped_unresolved_count,
    }
