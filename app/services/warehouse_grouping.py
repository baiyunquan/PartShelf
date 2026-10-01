"""Conservative, reusable physical grouping from native component records."""

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from contextlib import closing

from sqlalchemy.orm import Session

from app.models.custom_component import CustomComponent
from app.services.electrical_value_service import measurements_for_record, parse_measurements
from app.warehouse_grouping_config import CHIP_MODEL_ALIASES


@dataclass(frozen=True)
class StorageGroup:
    key: str
    kind: str
    label: str

    def as_dict(self):
        return {"key": self.key, "kind": self.kind, "label": self.label}


def _group(kind, identity, label):
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return StorageGroup(f"{kind}:{digest}", kind, label[:255])


def _normalized(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()


_FAMILIES = {
    "heat_insert": r"heat[ _-]?insert|热熔螺母|热嵌螺母",
    "screw": r"\bscrews?\b|螺钉|螺丝|顶丝",
    "bolt": r"\bbolts?\b|螺栓",
    "nut": r"\bnuts?\b|螺母",
    "washer": r"\bwashers?\b|垫圈|垫片",
    "spacer": r"\b(?:spacers?|standoffs?)\b|隔离柱|铜柱|支撑柱",
    "pin": r"\b(?:dowel[ _-]?pins?|spring[ _-]?pins?|roll[ _-]?pins?)\b|销钉|定位销",
    "bearing": r"\bbearings?\b|轴承",
    "gear": r"\bgears?\b|齿轮",
    "shaft": r"\bshafts?\b|轴类",
    "seal": r"\bseals?\b|油封|密封",
    "profile": r"\bprofiles?\b|型材|方管|板材",
}
_PASSIVES = {
    "capacitance": r"\bcapacitors?\b|电容",
    "resistance": r"\bresistors?\b|电阻",
    "inductance": r"\binductors?\b|电感",
}
_IC = r"\b(?:ic|ics|pmic|power management|integrated circuits?|microcontrollers?|amplifiers?|memory|interface|logic|drivers?|processors?)\b|芯片|集成电路|放大器|微控制器"


def mechanical_family(text):
    families = {family for family, pattern in _FAMILIES.items() if re.search(pattern, text, re.I)}
    if "heat_insert" in families:
        families.discard("nut")
    return next(iter(families)) if len(families) == 1 else None


def group_for_record(source: str, external_id: str, record: dict) -> StorageGroup:
    """Ignore packages, search aliases and fuzzy matches; unknown parts stay isolated."""
    fallback = _group("identity", [source, str(external_id)], f"{source}:{external_id}")
    category = " ".join(_normalized(record.get(field)) for field in
                        ("part_type", "category", "subcategory", "library", "category_group", "category_group_zh"))
    category = category.replace("_", " ")
    reference = _normalized(record.get("reference")).upper()
    is_chip = reference == "U" or bool(re.search(_IC, category, re.I))
    if is_chip:
        properties = record.get("properties") or record.get("properties_json") or {}
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except ValueError:
                properties = {}
        if not isinstance(properties, dict):
            properties = {}
        model = next((record.get(field) for field in ("mfr_part_number", "mfr") if record.get(field)), None)
        model = model or properties.get("Manufacturer Part Number") or properties.get("MPN")
        model = model or record.get("value") or record.get("lib_reference") or record.get("name")
        model = re.sub(r"\s+", "", _normalized(model)).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.+/_-]*", model) or not re.search(r"\d", model):
            return fallback
        base = CHIP_MODEL_ALIASES.get(model, model)
        return _group("chip", base, base)

    kinds = {kind for kind, pattern in _PASSIVES.items() if re.search(pattern, category, re.I)}
    if reference in {"C", "R", "L"}:
        kinds.add({"C": "capacitance", "R": "resistance", "L": "inductance"}[reference])
    # A complete numeric name is sufficient when a generic custom type is used.
    if not kinds:
        for field in ("value", "name"):
            value = _normalized(record.get(field))
            parsed = parse_measurements(value)
            if len(parsed) == 1 and parsed[0].start == 0 and parsed[0].end == len(value):
                kinds.add(parsed[0].kind)
    if len(kinds) == 1 and not re.search(r"\b(?:array|network)s?\b|排阻|阵列", category, re.I):
        kind = next(iter(kinds))
        values = {value for dimension, value in measurements_for_record(source, record) if dimension == kind}
        if len(values) == 1:
            value = next(iter(values))
            unit = {"capacitance": "F", "resistance": "Ω", "inductance": "H"}[kind]
            return _group(kind, value, f"{value} {unit}")
        return fallback
    if kinds:
        return fallback

    family = mechanical_family(_normalized(record.get("standard_name"))) or mechanical_family(category)
    if family:
        return _group("mechanical", family, family)
    return fallback


def native_record(db: Session, source: str, external_id: str) -> dict:
    """Read catalog data locally without dynamic fetching or alias indexes."""
    if source == "custom":
        if not str(external_id).isdigit():
            return {}
        component = db.get(CustomComponent, int(external_id))
        return {field: getattr(component, field) for field in
                ("name", "part_type", "manufacturer", "package", "description")} if component else {}
    from app.services import external_library_service as catalog
    if source == "fasteners":
        from app.services.fastener_variant_service import get_fastener_variant
        variant = get_fastener_variant(external_id)
        return variant.get("standard", {}) if variant else {}
    sources = {
        "jlcparts": (catalog.JLCPARTS_DB_PATH, ("jlc_components", "lcsc_components"), "lcsc"),
        "altium": (catalog.ALTIUM_DB_PATH, ("altium_components",), "id"),
        "kicad": (catalog.KICAD_DB_PATH, ("kicad_symbols",), "id"),
    }
    if source not in sources:
        return {}
    path, tables, id_column = sources[source]
    identity = str(external_id).lstrip("Cc") if source == "jlcparts" else str(external_id)
    if not identity.isdigit() or not path.exists():
        return {}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            for table in tables:
                if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    continue
                row = connection.execute(f"SELECT * FROM {table} WHERE {id_column} = ?", (int(identity),)).fetchone()
                if row:
                    return dict(row)
    except sqlite3.Error:
        return {}
    return {}


def group_for_part(db: Session, part) -> StorageGroup:
    return group_for_record(part.library_source, part.external_part_id,
                            native_record(db, part.library_source, part.external_part_id))
