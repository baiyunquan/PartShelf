"""Read-only BOM matching against the installed external component libraries."""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from app.services import external_library_service as libraries
from app.services.fastener_variant_service import (
    build_fastener_variant_id,
    normalize_length,
    normalize_nominal,
    parse_fastener_variant_id,
)


_UNITS = {"p": Decimal("1e-12"), "n": Decimal("1e-9"), "u": Decimal("1e-6"),
          "m": Decimal("1e-3"), "": Decimal(1), "k": Decimal("1e3"), "M": Decimal("1e6")}
_ATTRIBUTE = {"capacitor": "Capacitance", "resistor": "Resistance",
              "inductor": "Inductance", "crystal": "Frequency"}
_ALTIUM_FIELD = {"capacitor": "capacitance", "resistor": "resistance", "inductor": "inductance"}
_CATEGORY = {"capacitor": "Capacitors", "resistor": "Resistors", "inductor": "Inductors",
             "crystal": "Crystals", "led": "Optoelectronics"}
_COLORS = {"green": ("green", "绿"), "red": ("red", "红"),
           "blue": ("blue", "蓝"), "orange": ("orange", "橙"),
           "yellow": ("yellow", "黄"), "white": ("white", "白")}
_MECHANICAL_FAMILIES = {
    "screw": ("screw", "螺钉", "螺丝", "顶丝"),
    "bolt": ("bolt", "螺栓"),
    "nut": ("nut", "螺母"),
    "washer": ("washer", "垫圈", "垫片"),
    "spacer": ("spacer", "standoff", "隔离柱", "铜柱", "支撑柱"),
    "pin": ("dowel pin", "spring pin", "roll pin", "销钉", "定位销"),
    "bearing": ("bearing", "轴承"),
    "gear": ("gear", "齿轮"),
    "shaft": ("shaft", "轴类"),
    "seal": ("seal", "油封", "密封"),
    "profile": ("profile", "型材", "方管", "板材"),
}
_FASTENER_SHAPE_TERMS = (
    "hexagon socket", "socket head", "pan head", "countersunk", "flat head",
    "cross recessed", "slotted", "内六角", "十字槽", "一字槽", "沉头",
    "盘头", "圆头", "六角头", "滚花头", "圆柱头",
)


def component_kind(row: Dict[str, Any]) -> Optional[str]:
    category = f"{row.get('primary_category') or row.get('category') or ''} {row.get('secondary_category') or row.get('subcategory') or ''}".lower()
    footprint = (row.get("footprint") or row.get("package") or "").upper()
    designator = (row.get("designator") or "").upper()
    if mechanical_family(row):
        return "fastener"
    if "LED" in footprint or designator.startswith("LED") or "led" in category:
        return "led"
    if "oscillator" in (row.get("secondary_category") or row.get("subcategory") or "").lower():
        return "oscillator"
    if "crystal" in category or "oscillator" in category or "CRYSTAL" in footprint or designator.startswith(("Y", "X")):
        return "crystal"
    if "capacitor" in category or footprint.startswith("C0") or re.match(r"^C\d", designator):
        return "capacitor"
    if "resistor" in category or footprint.startswith("R0") or re.match(r"^R\d", designator):
        return "resistor"
    if "inductor" in category or "IND-SMD" in footprint or re.match(r"^L\d", designator):
        return "inductor"
    if any(word in category for word in ("integrated circuit", "power management ic", "microcontroller")) or re.match(r"^U\d", designator):
        return "ic"
    if "connector" in category or re.match(r"^J\d", designator):
        return "connector"
    if "transistor" in category or "mosfet" in category or re.match(r"^Q\d", designator):
        return "transistor"
    if "diode" in category or re.match(r"^D\d", designator):
        return "diode"
    return None


def mechanical_family(row: Dict[str, Any]) -> Optional[str]:
    """Classify a mechanical BOM row without consulting electronics-only fields."""
    text = " ".join(str(row.get(key) or "") for key in (
        "primary_category", "secondary_category", "designator", "comment", "value",
        "footprint", "manufacturer_part", "mechanical_standard", "mechanical_nominal",
    )).lower()
    for family, terms in _MECHANICAL_FAMILIES.items():
        if any(_mechanical_term_matches(text, term) for term in terms):
            return family
    if any(term in text for term in ("fastener", "standard part", "标准件", "机械件")):
        return "fastener"
    return None


def _mechanical_term_matches(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def parse_fastener_text(text: Any) -> Dict[str, Optional[str]]:
    """Extract a standard size and listed length from common BOM notation."""
    value = str(text or "").replace("×", "x").replace("✕", "x")
    normalized = value.upper()
    nominal = None
    length = None

    metric = re.search(
        r"(?<![A-Z0-9])M\s*(\d+(?:\.\d+)?)"
        r"(?:\s*-\s*\d+(?:\.\d+)?)?"
        r"(?:\s*[X*]\s*(\d+(?:\.\d+)?\s*(?:MM|INCH|IN|\")?))?",
        normalized,
    )
    if metric:
        nominal = normalize_nominal(f"M{metric.group(1)}")
        length = normalize_length(metric.group(2)) if metric.group(2) else None
    else:
        inch = re.search(
            r"(?<![A-Z0-9])(\d+\s*/\s*\d+)\s*(?:INCH|IN|\")?"
            r"(?:\s*[-–]\s*\d+)?"
            r"(?:\s*[X*]\s*(\d+(?:\.\d+)?\s*(?:MM|INCH|IN|\")?))?",
            normalized,
        )
        if inch:
            nominal = normalize_nominal(inch.group(1))
            length_raw = inch.group(2)
            if length_raw:
                has_unit = re.search(r"(?:MM|INCH|IN|\")$", length_raw.strip()) is not None
                length = normalize_length(length_raw if has_unit else f"{length_raw}in")

    return {"nominal": nominal, "length": length}


def measurement(text: Any, kind: Optional[str]) -> Optional[Decimal]:
    if not text or kind not in _ATTRIBUTE:
        return None
    value = str(text).replace("µ", "u").replace("μ", "u")
    suffix = {"capacitor": "f", "inductor": "h", "crystal": "hz", "resistor": "(?:Ω|Ω|ohm|r)"}[kind]
    match = re.search(rf"(?<![A-Za-z0-9])(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[pnumkKM]?)\s*{suffix}(?![A-Za-z])", value, re.I)
    if not match and kind == "resistor":
        match = re.search(r"(?<![A-Za-z0-9])(\d+)([RrKkMm])(\d+)(?![A-Za-z0-9])", value)
        if match:
            unit = "M" if match.group(2) == "M" else match.group(2).lower()
            return Decimal(f"{match.group(1)}.{match.group(3)}") * _UNITS.get(unit, Decimal(1))
    if not match and kind == "resistor":
        bare = re.search(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*([kKmM])(?![A-Za-z0-9])", value)
        if bare:
            unit = "M" if bare.group(2) == "M" else bare.group(2).lower()
            return Decimal(bare.group(1)) * _UNITS[unit]
    if not match:
        return None
    try:
        unit = match.group("unit")
        unit = "M" if unit == "M" else unit.lower()
        return Decimal(match.group("num")) * _UNITS[unit]
    except (InvalidOperation, KeyError):
        return None


def package_key(text: Any, kind: Optional[str] = None, pin_count: Any = None) -> Optional[str]:
    if not text:
        return None
    value = str(text).upper()
    size = re.search(r"L(\d+(?:\.\d+)?)-W(\d+(?:\.\d+)?)", value)
    if size:
        dimensions = (Decimal(size.group(1)), Decimal(size.group(2)))
        if dimensions == (Decimal("2.5"), Decimal("2.0")):
            return "1008"
        if dimensions == (Decimal("3.2"), Decimal("2.5")):
            return "3225-4P" if "4P" in value or str(pin_count) == "4" else "3225"
    if kind == "crystal":
        crystal = re.search(r"3225(?:[-_]?4P)?", value)
        if crystal:
            return "3225-4P" if "4P" in value or str(pin_count) == "4" else "3225"
    match = re.search(r"(?<!\d)(?:[CRL]|LED)?(0[2468]0[123568]|1008|1206|1210|1812|2010|2512)(?!\d)", value)
    if match:
        return match.group(1)
    package = re.search(r"\b(?:ESOP|SOIC|TSSOP|SSOP|MSOP|SOP|SOT|QFN|DFN|LQFP|QFP|BGA|TO)-?\d+(?:-\d+)?(?=$|[^A-Z0-9])", value)
    if package:
        result = package.group(0)
        return result[:-2] if result.endswith("-3") and result.startswith("SOT-23-") else result
    return None


def color_key(text: Any) -> Optional[str]:
    if not text:
        return None
    value = str(text).lower()
    for color, words in _COLORS.items():
        if any(word in value for word in words):
            return color
    return None


def row_measurement(row: Dict[str, Any], kind: Optional[str]) -> Optional[Decimal]:
    value = measurement(row.get("value"), kind)
    return value if value is not None else measurement(row.get("comment"), kind)


def row_color(row: Dict[str, Any]) -> Optional[str]:
    return color_key(row.get("value")) or color_key(row.get("comment"))


def row_conflicts(row: Dict[str, Any], kind: Optional[str]) -> List[str]:
    conflicts = []
    if kind == "fastener":
        conflicts.extend(fastener_spec_conflicts(row))
    value = measurement(row.get("value"), kind)
    comment = measurement(row.get("comment"), kind)
    if value is not None and comment is not None and value != comment:
        conflicts.append("value")
    if kind == "led":
        color = row_color(row)
        footprint_color = color_key(row.get("footprint"))
        if color and footprint_color and color != footprint_color:
            conflicts.append("color")
    return conflicts


def fastener_spec_conflicts(row: Dict[str, Any]) -> List[str]:
    specs = [parse_fastener_text(row.get(key)) for key in (
        "value", "comment", "footprint", "manufacturer_part", "mechanical_nominal",
    )]
    if row.get("mechanical_length"):
        specs.append({"nominal": None, "length": normalize_length(row["mechanical_length"])})
    conflicts = []
    for key in ("nominal", "length"):
        values = {spec[key] for spec in specs if spec.get(key)}
        if len(values) > 1:
            conflicts.append("dimensions")
            break
    return conflicts


def candidate_value(candidate: Dict[str, Any], kind: Optional[str]) -> Optional[Decimal]:
    if kind not in _ATTRIBUTE:
        return None
    attrs = candidate.get("attributes_dict") or candidate.get("parameters") or {}
    raw = attrs.get(_ATTRIBUTE[kind]) or candidate.get(_ALTIUM_FIELD.get(kind, ""))
    return measurement(raw, kind)


def candidate_conflicts(row: Dict[str, Any], candidate: Dict[str, Any], kind: Optional[str]) -> List[str]:
    conflicts = []
    candidate_kind = component_kind(candidate)
    if kind and candidate_kind and kind != candidate_kind:
        conflicts.append("type")
    wanted_package = package_key(row.get("footprint"), kind, row.get("pin_count"))
    found_package = package_key(candidate.get("package"), kind)
    if wanted_package and found_package and wanted_package != found_package:
        conflicts.append("package")
    wanted_value = row_measurement(row, kind)
    found_value = candidate_value(candidate, kind)
    if wanted_value is not None and found_value is not None and wanted_value != found_value:
        conflicts.append("value")
    if kind == "led":
        wanted_color = row_color(row)
        attrs = candidate.get("attributes_dict") or candidate.get("parameters") or {}
        found_color = color_key(attrs.get("Illumination Color") or attrs.get("Emitted Color") or candidate.get("description"))
        if wanted_color and found_color and wanted_color != found_color:
            conflicts.append("color")
    return conflicts


def normalized_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    match = re.fullmatch(r"[Cc]?(\d{3,10})", str(value).strip())
    return str(int(match.group(1))) if match else None


class BomMatcher:
    def __init__(self):
        self.jlc = libraries.get_connection(libraries.JLCPARTS_DB_PATH)
        self.altium = libraries.get_connection(libraries.ALTIUM_DB_PATH)
        self.fasteners = libraries.get_connection(libraries.FASTENERS_DB_PATH)
        self._cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        self._fastener_rows: Optional[List[Dict[str, Any]]] = None

    def close(self):
        for conn in (self.jlc, self.altium, self.fasteners):
            if conn:
                conn.close()

    def _load_fastener_rows(self) -> List[Dict[str, Any]]:
        if self._fastener_rows is not None:
            return self._fastener_rows
        self._fastener_rows = []
        if not self.fasteners:
            return self._fastener_rows

        titles = {
            row["table_name"]: json.loads(row["titles_json"] or "[]")
            for row in self.fasteners.execute("SELECT table_name, titles_json FROM fastener_table_titles")
        }
        tables: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.fasteners.execute("SELECT table_name, row_key, data_json FROM fastener_tables"):
            try:
                values = json.loads(row["data_json"] or "[]")
            except (TypeError, ValueError):
                values = []
            tables.setdefault(row["table_name"], []).append({"key": row["row_key"], "values": values})

        standards = self.fasteners.execute("SELECT * FROM fastener_standards").fetchall()
        for raw_standard in standards:
            standard = dict(raw_standard)
            param_table = standard.get("param_table_name")
            if not param_table:
                continue
            param_titles = titles.get(param_table, [])
            length_table = standard.get("length_table_name")
            length_rows = tables.get(length_table, []) if length_table else []
            length_keys = {normalize_length(row["key"]): row["key"] for row in length_rows}
            for param in tables.get(param_table, []):
                nominal = param["key"]
                dimensions = dict(zip(param_titles, param["values"]))
                self._fastener_rows.append({
                    "standard": standard,
                    "nominal": nominal,
                    "nominal_key": normalize_nominal(nominal),
                    "dimensions": dimensions,
                    "has_length": bool(standard.get("has_length")),
                    "length_keys": length_keys,
                })
        return self._fastener_rows

    def _fastener_standard_code(self, row: Dict[str, Any]) -> Optional[str]:
        explicit = row.get("mechanical_standard") or ""
        text = " ".join(str(row.get(key) or "") for key in (
            "value", "comment", "footprint", "manufacturer_part", "mechanical_standard",
        ))
        normalized_text = re.sub(r"[^a-z0-9]", "", text.lower())
        rows = self._load_fastener_rows()
        standards = {item["standard"]["standard_code"] for item in rows}
        if explicit:
            standards.add(str(explicit).strip())
        for code in sorted(standards, key=len, reverse=True):
            code_key = re.sub(r"[^a-z0-9]", "", code.lower())
            if code_key and code_key in normalized_text:
                return code
        return None

    @staticmethod
    def _fastener_text(row: Dict[str, Any]) -> str:
        return " ".join(str(row.get(key) or "") for key in (
            "primary_category", "secondary_category", "designator", "value", "comment",
            "footprint", "manufacturer_part", "mechanical_standard", "mechanical_nominal",
        )).lower()

    @staticmethod
    def _fastener_category_matches(family: Optional[str], standard: Dict[str, Any], text: str) -> bool:
        if not family:
            return True
        category = f"{standard.get('category_group_zh') or ''} {standard.get('category_group') or ''} {standard.get('description') or ''}".lower()
        terms = _MECHANICAL_FAMILIES.get(family, ())
        if any(term in category for term in terms):
            return True
        if family == "screw" and "螺栓" in category and "螺钉" not in category and "screw" not in category:
            return False
        return family == "screw" and "bolt" in category and any(t in text for t in ("bolt", "螺栓"))

    def fastener_match(self, row: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        """Return dimension-compatible mechanical variants; incomplete rows never bind."""
        if fastener_spec_conflicts(row):
            return {"items": [], "missing_dimensions": [], "reason": "conflict"}
        data = parse_fastener_text(" ".join(str(row.get(key) or "") for key in (
            "value", "comment", "footprint", "manufacturer_part", "mechanical_nominal", "mechanical_length",
        )))
        explicit_nominal = row.get("mechanical_nominal")
        if explicit_nominal:
            explicit_spec = parse_fastener_text(explicit_nominal)
            data["nominal"] = explicit_spec["nominal"] or normalize_nominal(explicit_nominal)
        explicit_length = row.get("mechanical_length")
        if explicit_length:
            data["length"] = normalize_length(explicit_length)
        standard_code = self._fastener_standard_code(row)
        family = mechanical_family(row)
        text = self._fastener_text(row)
        records = self._load_fastener_rows()

        if not data["nominal"]:
            return {"items": [], "missing_dimensions": ["nominal"], "reason": "incomplete_dimensions"}

        nominal_matches = [record for record in records
                           if record["nominal_key"] == data["nominal"]
                           and self._fastener_category_matches(family, record["standard"], text)]
        if standard_code:
            standard_key = re.sub(r"[^a-z0-9]", "", standard_code.lower())
            nominal_matches = [record for record in nominal_matches
                               if re.sub(r"[^a-z0-9]", "", record["standard"]["standard_code"].lower()) == standard_key]
            if not nominal_matches:
                return {"items": [], "missing_dimensions": [], "reason": "no_dimension_match"}

        length_required = any(record["has_length"] for record in nominal_matches)
        if length_required and not data["length"]:
            missing = ["length"]
            if not standard_code and len({r["standard"]["standard_code"] for r in nominal_matches}) > 1:
                missing.append("standard_or_head_geometry")
            return {"items": [], "missing_dimensions": missing, "reason": "incomplete_dimensions"}

        matched_records = []
        for record in nominal_matches:
            if record["has_length"]:
                requested_length = data["length"]
                actual_length = record["length_keys"].get(requested_length)
                if actual_length is None and requested_length and requested_length.isdecimal():
                    actual_length = record["length_keys"].get(f"{requested_length}in")
                if actual_length is None:
                    continue
                record_length = actual_length
            else:
                if data["length"]:
                    continue
                record_length = None
            matched_records.append((record, record_length))

        if not matched_records:
            return {"items": [], "missing_dimensions": [], "reason": "no_dimension_match"}

        # Without a standard identifier, a generic family and nominal/length alone
        # may leave several standards. Keep those candidates for explicit review.
        ambiguous_standard = False
        shape_tokens = [term for term in _FASTENER_SHAPE_TERMS if term in text]
        if not standard_code and len({r[0]["standard"]["standard_code"] for r in matched_records}) > 1:
            if shape_tokens:
                narrowed = [pair for pair in matched_records if any(
                    token in (pair[0]["standard"].get("category_group_zh", "") + " " + pair[0]["standard"].get("description", "")).lower()
                    for token in shape_tokens
                )]
                if narrowed:
                    matched_records = narrowed
            ambiguous_standard = len({r[0]["standard"]["standard_code"] for r in matched_records}) > 1

        candidates = []
        for record, record_length in matched_records:
            standard = record["standard"]
            external_id = build_fastener_variant_id(standard["standard_code"], record["nominal"], record_length)
            size = record["nominal"]
            if record_length:
                size += f" × {record_length}"
                if "in" not in size.lower():
                    size += " mm"
            name = f"{standard['standard_code']} {size}"
            candidates.append({
                "library_source": "fasteners",
                "external_part_id": external_id,
                "name": name,
                "manufacturer": standard.get("authority") or "",
                "authority": standard.get("authority") or "",
                "package": standard.get("category_group_zh") or standard.get("category_group") or "",
                "value": size,
                "stock": 0,
                "standard_code": standard["standard_code"],
                "nominal": record["nominal"],
                "length": record_length,
                "dimensions": record["dimensions"],
                "match_reason": "dimension_match",
                "conflicts": [],
            })

        if query:
            def search_key(value: str) -> str:
                normalized = str(value or "").lower().replace("×", "x").replace("✕", "x").replace("*", "x")
                return re.sub(r"\s+", "", normalized)

            query_key = search_key(query)
            candidates = [candidate for candidate in candidates if query_key in search_key(
                f"{candidate['standard_code']} {candidate['name']} {candidate['package']}"
            )]

        unique = {candidate["external_part_id"]: candidate for candidate in candidates}
        ordered = sorted(unique.values(), key=lambda candidate: (candidate["standard_code"], candidate["external_part_id"]))
        missing = ["standard_or_head_geometry"] if ambiguous_standard else []
        reason = "no_dimension_match" if not ordered else (
            "ambiguous_dimensions" if len(ordered) != 1 or ambiguous_standard else "dimension_match"
        )
        return {"items": ordered[:10], "missing_dimensions": missing, "reason": reason}

    def validate_fastener_match(self, row: Dict[str, Any], external_part_id: str) -> bool:
        identity = parse_fastener_variant_id(external_part_id)
        if not identity:
            return False
        result = self.fastener_match(row)
        return any(candidate["external_part_id"] == external_part_id for candidate in result["items"])

    @staticmethod
    def _from_jlc(record) -> Dict[str, Any]:
        item = dict(record)
        try:
            item["attributes_dict"] = json.loads(item.get("attributes") or "{}")
        except (ValueError, TypeError):
            item["attributes_dict"] = {}
        item.update(library_source="jlcparts", external_part_id=str(item["lcsc"]),
                    name=item.get("mfr") or f"C{item['lcsc']}",
                    stock=item.get("stock") or 0)
        return item

    @staticmethod
    def _from_altium(record) -> Dict[str, Any]:
        item = dict(record)
        try:
            item["parameters"] = json.loads(item.get("parameters_json") or "{}")
        except (ValueError, TypeError):
            item["parameters"] = {}
        item.update(library_source="altium", external_part_id=str(item["id"]),
                    name=item.get("lib_reference") or item.get("mfr_part_number") or str(item["id"]), stock=0)
        return item

    def exact_code(self, code: str) -> List[Dict[str, Any]]:
        matches = []
        if self.jlc:
            matches.extend(self._from_jlc(r) for r in self.jlc.execute(
                "SELECT * FROM jlc_components WHERE lcsc = ?", (int(code),)))
        if self.altium:
            matches.extend(self._from_altium(r) for r in self.altium.execute(
                "SELECT * FROM altium_components WHERE lcsc_part IN (?, ?)", (f"C{code}", code)))
        return matches

    def lookup(self, source: str, external_id: str) -> Optional[Dict[str, Any]]:
        if source == "jlcparts" and self.jlc and external_id.isdigit():
            record = self.jlc.execute("SELECT * FROM jlc_components WHERE lcsc = ?", (int(external_id),)).fetchone()
            return self._from_jlc(record) if record else None
        if source == "altium" and self.altium and external_id.isdigit():
            record = self.altium.execute("SELECT * FROM altium_components WHERE id = ?", (int(external_id),)).fetchone()
            return self._from_altium(record) if record else None
        return None

    def exact_model(self, model: str) -> List[Dict[str, Any]]:
        model = (model or "").strip()
        if len(model) < 4:
            return []
        matches = []
        if self.jlc:
            matches.extend(self._from_jlc(r) for r in self.jlc.execute(
                "SELECT * FROM jlc_components WHERE mfr = ?", (model,)))
        if self.altium:
            matches.extend(self._from_altium(r) for r in self.altium.execute(
                "SELECT * FROM altium_components WHERE lib_reference = ? OR mfr_part_number = ?", (model, model)))
        return matches

    def _by_package(self, source: str, kind: str, package: str) -> List[Dict[str, Any]]:
        key = (source, kind, package)
        if key in self._cache:
            return self._cache[key]
        conn = self.jlc if source == "jlcparts" else self.altium
        if not conn:
            return []
        category = _CATEGORY[kind]
        package_sql = "package LIKE ?"
        package_arg = f"%{package}%" if package.startswith("3225") else f"{package}%"
        query = f"SELECT * FROM {'jlc_components' if source == 'jlcparts' else 'altium_components'} WHERE category LIKE ? AND {package_sql}"
        convert = self._from_jlc if source == "jlcparts" else self._from_altium
        rows = [convert(r) for r in conn.execute(query, (f"{category}%", package_arg))]
        self._cache[key] = rows
        return rows

    def suggestions(self, row: Dict[str, Any], kind: Optional[str], exclude: Optional[set] = None) -> List[Dict[str, Any]]:
        exclude = exclude or set()
        wanted_package = package_key(row.get("footprint"), kind, row.get("pin_count"))
        wanted_value = row_measurement(row, kind)
        wanted_color = row_color(row)
        candidates = []
        if kind in _CATEGORY and wanted_package and (wanted_value is not None or kind == "led" and wanted_color):
            for source in ("jlcparts", "altium"):
                for candidate in self._by_package(source, kind, wanted_package):
                    identity = (source, candidate["external_part_id"])
                    if identity in exclude or package_key(candidate.get("package"), kind) != wanted_package:
                        continue
                    if candidate_conflicts(row, candidate, kind):
                        continue
                    if kind == "led":
                        attrs = candidate.get("attributes_dict") or candidate.get("parameters") or {}
                        found_color = color_key(attrs.get("Illumination Color") or attrs.get("Emitted Color") or candidate.get("description"))
                        if found_color != wanted_color:
                            continue
                    elif candidate_value(candidate, kind) != wanted_value:
                        continue
                    candidates.append(candidate)
        # An exact model is useful for ICs and connectors too, but never binds automatically.
        model = (row.get("manufacturer_part") or "").strip()
        candidates.extend(self.exact_model(model))
        unique = {}
        for candidate in candidates:
            identity = (candidate["library_source"], candidate["external_part_id"])
            if identity not in exclude and not candidate_conflicts(row, candidate, kind):
                unique[identity] = candidate
        ordered = sorted(unique.values(), key=lambda candidate: (
            0 if candidate["library_source"] == "jlcparts" else 1,
            -candidate["stock"], candidate["external_part_id"]))
        return [public_candidate(candidate, "parameter_package" if kind else "exact_model") for candidate in ordered[:10]]

    def search(self, row: Dict[str, Any], query: str, lang: str = "zh") -> List[Dict[str, Any]]:
        kind = component_kind(row)
        query = (query or "").strip()
        if kind == "fastener":
            return self.fastener_match(row, query=query)["items"]
        if not query:
            return self.suggestions(row, kind)
        code = normalized_code(query)
        if code:
            candidates = self.exact_code(code)
            if not candidates:
                return self.suggestions(row, kind)
        elif measurement(query, kind) is not None or kind == "led" and color_key(query):
            searched_row = dict(row, value=query, comment=query, manufacturer_part="")
            results = self.suggestions(searched_row, kind)
            for result in results:
                candidate = self.lookup(result["library_source"], result["external_part_id"])
                result["conflicts"] = candidate_conflicts(row, candidate, kind) if candidate else []
            return results
        else:
            candidates = self.exact_model(query)
            if not candidates:
                broad = libraries.search_all_libraries(query, limit_each=10, lang=lang)
                candidates.extend(self._from_jlc(record) for record in broad["jlcparts"])
                candidates.extend(self._from_altium(record) for record in broad["altium"])
                for record in broad["kicad"]:
                    candidates.append({
                        "library_source": "kicad", "external_part_id": str(record["id"]),
                        "name": record.get("name") or record.get("value") or str(record["id"]),
                        "category": record.get("library"), "package": record.get("footprint"),
                        "manufacturer": "", "stock": 0, "description": record.get("description"),
                    })
                if not candidates:
                    return self.suggestions(row, kind)
        candidates = sorted(candidates, key=lambda candidate: (
            {"jlcparts": 0, "altium": 1, "kicad": 2}.get(candidate["library_source"], 3),
            len(candidate_conflicts(row, candidate, kind)), -candidate.get("stock", 0),
            candidate["external_part_id"],
        ))
        unique = {}
        for candidate in candidates:
            identity = (candidate["library_source"], candidate["external_part_id"])
            unique[identity] = public_candidate(candidate, "manual_search", candidate_conflicts(row, candidate, kind))
        return list(unique.values())[:10]


def public_candidate(candidate: Dict[str, Any], reason: str, conflicts: Optional[List[str]] = None) -> Dict[str, Any]:
    kind = component_kind(candidate)
    attrs = candidate.get("attributes_dict") or candidate.get("parameters") or {}
    return {
        "library_source": candidate["library_source"],
        "external_part_id": candidate["external_part_id"],
        "name": candidate["name"],
        "manufacturer": candidate.get("manufacturer") or "",
        "package": candidate.get("package") or "",
        "stock": candidate.get("stock") or 0,
        "value": attrs.get(_ATTRIBUTE.get(kind, "")) or candidate.get(_ALTIUM_FIELD.get(kind, "")) or attrs.get("Illumination Color") or attrs.get("Emitted Color") or "",
        "voltage": attrs.get("Voltage Rating") or candidate.get("voltage_rating") or "",
        "tolerance": attrs.get("Tolerance") or candidate.get("tolerance") or "",
        "lcsc_part": candidate.get("lcsc_part") or (f"C{candidate['lcsc']}" if candidate["library_source"] == "jlcparts" else ""),
        "match_reason": reason,
        "conflicts": conflicts or [],
    }
