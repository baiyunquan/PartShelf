#!/usr/bin/env python3
"""Measure visible list content and generate stable per-page table widths."""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSS_START = "/* generated list widths: start */"
CSS_END = "/* generated list widths: end */"
SINGLE_SEARCH_ANCHOR = "const thead = document.getElementById('singleTableHeader');"
BATCH_SIZE = 1000
NORMAL_BUDGET = 1116
BOM_BUDGET = 1440


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    section: str
    key: str
    control_px: int = 0
    fallback_px: int = 64
    first_text: bool = False
    max_width: int = 320


@dataclass(frozen=True)
class LayoutSpec:
    name: str
    template: str
    css_file: str
    marker: str
    columns: tuple[ColumnSpec, ...]
    budget_px: int = NORMAL_BUDGET


@dataclass(frozen=True)
class ColumnMeasurements:
    name: str
    header_width: int
    control_width: int
    median_width: int
    p95_width: int
    p99_width: int
    first_text: bool = False
    max_width: int = 320
    fallback_width: int = 0


def _column(name: str, section: str, key: str, *, control: int = 0,
            fallback: int = 64, first: bool = False, cap: int = 320) -> ColumnSpec:
    return ColumnSpec(name, section, key, control, fallback, first, cap)


LAYOUTS: dict[str, LayoutSpec] = {
    "inventory": LayoutSpec("inventory", "inventory.html", "inventory.css", "parts-table-body", (
        _column("id", "inventory", "th_id", control=72, fallback=72, cap=90),
        _column("name", "inventory", "th_name", first=True, cap=480),
        _column("source", "inventory", "th_source", cap=180),
        _column("package", "inventory", "th_package", cap=220),
        _column("location", "inventory", "th_location", cap=220),
        _column("warehouse", "inventory", "th_warehouse", cap=240),
        _column("quantity", "inventory", "th_quantity", control=96, fallback=96, cap=120),
        _column("projects", "inventory", "th_projects", cap=280),
        _column("actions", "inventory", "th_actions", control=100, fallback=100, cap=140),
    )),
    "jlcparts": LayoutSpec("jlcparts", "libraries_jlcparts.html", "libraries_jlcparts.css", "tableBody", (
        _column("image", "libraries_jlcparts", "th_image", control=72, fallback=72, cap=72),
        _column("specs", "libraries_jlcparts", "th_specs", first=True, cap=480),
        _column("package", "libraries_jlcparts", "th_package", cap=220),
        _column("mfr", "libraries_jlcparts", "th_mfr", cap=260),
        _column("category", "libraries_jlcparts", "th_category", cap=280),
        _column("manufacturer", "libraries_jlcparts", "th_manufacturer", cap=280),
        _column("lcsc", "libraries_jlcparts", "th_lcsc", cap=160),
        _column("stock", "libraries_jlcparts", "th_stock", cap=150),
        _column("price", "libraries_jlcparts", "th_price", cap=200),
        _column("actions", "libraries_jlcparts", "th_actions", control=160, fallback=160, cap=200),
    )),
    "altium": LayoutSpec("altium", "libraries_altium.html", "libraries_altium.css", "tableBody", (
        _column("specs", "libraries_altium", "th_specs", first=True, cap=480),
        _column("package", "libraries_altium", "th_package", cap=220),
        _column("lib_ref", "libraries_altium", "th_lib_ref", cap=300),
        _column("category", "libraries_altium", "th_category", cap=280),
        _column("manufacturer", "libraries_altium", "th_manufacturer", cap=280),
        _column("lcsc_part", "libraries_altium", "th_lcsc_part", cap=200),
        _column("type", "libraries_altium", "th_type", cap=200),
        _column("actions", "libraries_altium", "th_actions", control=160, fallback=160, cap=200),
    )),
    "kicad": LayoutSpec("kicad", "libraries_kicad.html", "libraries_kicad.css", "tableBody", (
        _column("name", "libraries_kicad", "th_name", first=True, cap=480),
        _column("library", "libraries_kicad", "th_library", cap=260),
        _column("reference", "libraries_kicad", "th_reference", cap=180),
        _column("extends", "libraries_kicad", "th_extends", cap=280),
        _column("footprint", "libraries_kicad", "th_footprint", cap=320),
        _column("description", "libraries_kicad", "th_description", cap=320),
        _column("actions", "libraries_kicad", "th_actions", control=160, fallback=160, cap=200),
    )),
    "fasteners": LayoutSpec("fasteners", "libraries_fasteners.html", "libraries_fasteners.css", "tableBody", (
        _column("code", "libraries_fasteners", "th_code", first=True, cap=360),
        _column("authority", "libraries_fasteners", "th_authority", cap=220),
        _column("domain", "libraries_fasteners", "filter_domain", cap=220),
        _column("category", "libraries_fasteners", "th_category", cap=260),
        _column("description", "libraries_fasteners", "th_description", cap=420),
        _column("has_length", "libraries_fasteners", "th_has_length", cap=200),
        _column("actions", "libraries_fasteners", "th_actions", control=140, fallback=140, cap=180),
    )),
    "search-inventory-overview": LayoutSpec("search-inventory-overview", "search.html", "search.css", "overview-inventory-body", (
        _column("id", "inventory", "th_id", control=72, fallback=72, cap=90),
        _column("name", "inventory", "th_name", first=True, cap=480),
        _column("package", "inventory", "th_package", cap=220),
        _column("location", "inventory", "th_location", cap=220),
        _column("quantity", "inventory", "th_quantity", control=96, fallback=96, cap=120),
        _column("actions", "inventory", "th_actions", control=100, fallback=100, cap=140),
    )),
    "search-jlcparts-overview": LayoutSpec("search-jlcparts-overview", "search.html", "search.css", "overview-jlcparts-body", ()),
    "search-altium-overview": LayoutSpec("search-altium-overview", "search.html", "search.css", "overview-altium-body", ()),
    "search-kicad-overview": LayoutSpec("search-kicad-overview", "search.html", "search.css", "overview-kicad-body", ()),
    "search-fasteners-overview": LayoutSpec("search-fasteners-overview", "search.html", "search.css", "overview-fasteners-body", ()),
    "search-inventory-single": LayoutSpec("search-inventory-single", "search.html", "search.css", "singleTableBody", ()),
    "search-jlcparts-single": LayoutSpec("search-jlcparts-single", "search.html", "search.css", "singleViewTable", ()),
    "search-altium-single": LayoutSpec("search-altium-single", "search.html", "search.css", "singleViewTable", ()),
    "search-kicad-single": LayoutSpec("search-kicad-single", "search.html", "search.css", "singleViewTable", ()),
    "search-fasteners-single": LayoutSpec("search-fasteners-single", "search.html", "search.css", "singleViewTable", ()),
    "projects": LayoutSpec("projects", "projects.html", "projects.css", "projects-table-body", (
        _column("id", "projects", "th_id", control=76, fallback=76, cap=100),
        _column("name", "projects", "th_name", first=True, cap=480),
        _column("description", "projects", "th_description", cap=360),
        _column("parts_count", "projects", "th_parts_count", control=150, fallback=150, cap=200),
        _column("actions", "projects", "th_actions", control=180, fallback=180, cap=220),
    )),
    "project-bom": LayoutSpec("project-bom", "project_details.html", "project_details.css", "bom-table-body", (
        _column("part_name", "project_details", "th_part_name", first=True, cap=480),
        _column("manufacturer", "project_details", "th_manufacturer", cap=280),
        _column("package", "project_details", "th_package", cap=220),
        _column("type", "project_details", "th_type", cap=200),
        _column("available", "project_details", "th_available", cap=150),
        _column("needed", "project_details", "th_needed", cap=150),
        _column("shortage", "project_details", "th_shortage", cap=150),
        _column("actions", "project_details", "th_actions", control=170, fallback=170, cap=210),
    )),
    "project-shortage": LayoutSpec("project-shortage", "project_details.html", "project_details.css", "shortage-table-body", (
        _column("part_name", "project_details", "th_part_name", first=True, cap=480),
        _column("package", "project_details", "th_package", cap=220),
        _column("available", "project_details", "th_available", cap=150),
        _column("needed", "project_details", "th_needed", cap=150),
        _column("shortage", "project_details", "th_shortage", cap=150),
    )),
    "procurement": LayoutSpec("procurement", "procurement.html", "procurement.css", "procurement-table-body", (
        _column("part_name", "procurement", "th_part_name", first=True, cap=480),
        _column("package", "procurement", "th_package", cap=220),
        _column("type", "procurement", "th_type", cap=200),
        _column("available", "procurement", "th_available", cap=150),
        _column("total_needed", "procurement", "th_total_needed", cap=180),
        _column("shortage", "procurement", "th_shortage", cap=180),
        _column("projects", "procurement", "th_projects", cap=320),
    )),
    "bom-preview": LayoutSpec("bom-preview", "bom_import.html", "bom_import.css", "bomPreviewTable", (
        _column("select", "bom_import", "th_select", control=70, fallback=70, cap=90),
        _column("row", "bom_import", "th_row", control=80, fallback=80, cap=110),
        _column("component", "bom_import", "th_component", first=True, cap=480),
        _column("designator", "bom_import", "th_designator", cap=300),
        _column("footprint", "bom_import", "th_footprint", cap=360),
        _column("quantity", "bom_import", "th_quantity", control=90, fallback=90, cap=120),
        _column("match_status", "bom_import", "th_match_status", cap=240),
        _column("matched_part", "bom_import", "th_matched_part", cap=420),
    ), BOM_BUDGET),
}


def _library_columns(prefix: str, section: str) -> tuple[ColumnSpec, ...]:
    source = LAYOUTS[prefix].columns
    return source


def _set_layout_columns(name: str, columns: tuple[ColumnSpec, ...]) -> None:
    previous = LAYOUTS[name]
    LAYOUTS[name] = LayoutSpec(
        previous.name, previous.template, previous.css_file, previous.marker,
        columns, previous.budget_px,
    )


for _layout_name in ("search-jlcparts-overview", "search-jlcparts-single"):
    _set_layout_columns(_layout_name, _library_columns("jlcparts", "libraries_jlcparts"))
for _layout_name in ("search-altium-overview", "search-altium-single"):
    _set_layout_columns(_layout_name, (
        _column("specs", "libraries_altium", "th_specs", first=True, cap=480),
        _column("package", "libraries_altium", "th_package", cap=220),
        _column("lib_ref", "libraries_altium", "th_lib_ref", cap=300),
        _column("category", "libraries_altium", "th_category", cap=280),
        _column("manufacturer", "libraries_altium", "th_manufacturer", cap=280),
        _column("lcsc_part", "libraries_altium", "th_lcsc_part", cap=200),
        _column("actions", "libraries_altium", "th_actions", control=160, fallback=160, cap=200),
    ))
for _layout_name in ("search-kicad-overview", "search-kicad-single"):
    _set_layout_columns(_layout_name, (
        _column("name", "libraries_kicad", "th_name", first=True, cap=480),
        _column("library", "libraries_kicad", "th_library", cap=260),
        _column("footprint", "libraries_kicad", "th_footprint", cap=320),
        _column("actions", "libraries_kicad", "th_actions", control=160, fallback=160, cap=200),
    ))
_fastener_search_cols = (
    _column("code", "libraries_fasteners", "th_code", first=True, cap=360),
    _column("authority", "libraries_fasteners", "th_authority", cap=220),
    _column("category", "libraries_fasteners", "th_category", cap=260),
    _column("description", "libraries_fasteners", "th_description", cap=420),
    _column("actions", "libraries_fasteners", "th_actions", control=140, fallback=140, cap=180),
)
_set_layout_columns("search-fasteners-overview", _fastener_search_cols)
_set_layout_columns("search-fasteners-single", _fastener_search_cols[:4] + (
    _column("has_length", "libraries_fasteners", "th_has_length", cap=200),
    _fastener_search_cols[-1],
))
_set_layout_columns("search-inventory-single", LAYOUTS["search-inventory-overview"].columns)


@dataclass
class WidthHistogram:
    bins: list[int] = field(default_factory=lambda: [0] * 4097)
    char_bins: list[int] = field(default_factory=lambda: [0] * 4097)
    count: int = 0
    sources: dict[str, int] = field(default_factory=dict)

    def add_width(self, width: int, char_count: int = 0, source: str | None = None) -> None:
        self.bins[min(max(int(width), 0), len(self.bins) - 1)] += 1
        self.char_bins[min(max(int(char_count), 0), len(self.char_bins) - 1)] += 1
        self.count += 1
        if source:
            self.sources[source] = self.sources.get(source, 0) + 1

    def quantile(self, q: float) -> int:
        if self.count == 0:
            return 0
        target = max(1, math.ceil(self.count * q))
        seen = 0
        for width, count in enumerate(self.bins):
            seen += count
            if seen >= target:
                return width
        return len(self.bins) - 1

    def quantile_chars(self, q: float) -> int:
        if self.count == 0:
            return 0
        target = max(1, math.ceil(self.count * q))
        seen = 0
        for length, count in enumerate(self.char_bins):
            seen += count
            if seen >= target:
                return length
        return len(self.char_bins) - 1


@lru_cache(maxsize=262144)
def _estimate_text_width_cached(text: str, font_size: float) -> int:
    """Estimate rendered CSS pixels using Unicode classes and a system-font average."""
    width = 0.0
    for char in text:
        category = unicodedata.category(char)
        if category in {"Mn", "Me", "Cf"}:
            continue
        east_width = unicodedata.east_asian_width(char)
        if east_width in {"W", "F"}:
            factor = 1.0
        elif char.isspace():
            factor = 0.28
        elif char.isdigit():
            factor = 0.56
        elif char.isupper():
            factor = 0.62
        elif category.startswith("P"):
            factor = 0.36
        elif category.startswith("S"):
            factor = 0.62
        else:
            factor = 0.53
        width += font_size * factor
    return int(math.ceil(width))


def estimate_text_width(text: object, font_size: float = 16) -> int:
    return _estimate_text_width_cached("" if text is None else str(text), font_size)


def choose_column_widths(columns: Sequence[ColumnMeasurements], budget_px: int) -> list[int]:
    """Keep short cells at their natural floor, then allocate equal space to peers."""
    if not columns:
        return []
    floors = [max(c.header_width, c.control_width, c.median_width, c.fallback_width) for c in columns]
    targets = [
        max(floor, min(c.max_width, c.p99_width if c.first_text else c.p95_width))
        for floor, c in zip(floors, columns)
    ]
    widths = floors[:]
    priority_index = next((i for i, column in enumerate(columns) if column.first_text), None)
    if priority_index is not None:
        widths[priority_index] = targets[priority_index]
    floor_total = sum(floors)
    priority_extra = sum(widths) - floor_total
    available = max(budget_px, floor_total + priority_extra) - sum(widths)
    peers = [
        i for i, column in enumerate(columns)
        if i != priority_index and targets[i] > widths[i]
    ]
    while available > 0 and peers:
        share = max(1, available // len(peers))
        next_peers: list[int] = []
        spent = 0
        for index in peers:
            grant = min(share, targets[index] - widths[index], available - spent)
            if grant > 0:
                widths[index] += grant
                spent += grant
            if widths[index] < targets[index]:
                next_peers.append(index)
        if spent == 0:
            break
        available -= spent
        peers = next_peers
    return widths


@dataclass
class LayoutMeasurements:
    columns: dict[str, WidthHistogram]
    sources: dict[str, int] = field(default_factory=dict)

    @classmethod
    def for_layout(cls, spec: LayoutSpec) -> "LayoutMeasurements":
        return cls({column.name: WidthHistogram() for column in spec.columns})

    def observe(self, column: str, value: object, *, font_size: float = 16, source: str | None = None) -> None:
        values = value if isinstance(value, (tuple, list)) else (value,)
        measured_value = max(values, key=lambda item: estimate_text_width(item, font_size), default="")
        measured = estimate_text_width(measured_value, font_size)
        measured_text = "" if measured_value is None else str(measured_value)
        char_count = sum(1 for char in measured_text if unicodedata.category(char) not in {"Mn", "Me", "Cf"})
        self.columns[column].add_width(measured, char_count, source)


def _translate_header(catalog: dict, spec: ColumnSpec, language: str) -> str:
    return str(catalog.get(language, {}).get(spec.section, {}).get(spec.key, spec.key))


def _read_catalogs() -> dict:
    return {
        language: json.loads((ROOT / "app" / "i18n" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("zh", "en")
    }


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _record_source(measurements: dict[str, LayoutMeasurements], source: str, count: int,
                   layouts: Iterable[str]) -> None:
    for layout in layouts:
        result = measurements[layout]
        result.sources[source] = result.sources.get(source, 0) + count


def _observe(measurements: dict[str, LayoutMeasurements], layout: str, values: dict[str, object],
             *, source: str | None = None) -> None:
    result = measurements[layout]
    for column, value in values.items():
        if column in result.columns and value not in (None, ""):
            result.observe(column, value, source=source)


def _default_value(value: object, fallback: str = "-") -> str:
    return str(value) if value not in (None, "") else fallback


def _first_price(price: object) -> str:
    text = str(price or "")
    first = text.split(",", 1)[0]
    return first.split(":", 1)[-1] if first else "-"


def _altium_specs(row: dict, description_limit: int = 40) -> str:
    parts = [str(row.get(key)) for key in (
        "resistance", "capacitance", "inductance", "tolerance", "voltage_rating", "power_rating"
    ) if row.get(key)]
    if parts:
        return ", ".join(parts)
    description = str(row.get("description") or "")
    if len(description) > description_limit:
        return description[:description_limit - 2] + "..."
    return description or "-"


def _scan_jlc(path: Path, measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int]) -> None:
    if not path.exists():
        row_counts["jlcparts"] = 0
        return
    from app.i18n.category_i18n import category_i18n
    from app.services.external_library_service import extract_jlcparts_specs

    layouts = ("jlcparts",)
    connection = _connect_readonly(path)
    try:
        if not _table_exists(connection, "jlc_components"):
            row_counts["jlcparts"] = 0
            return
        cursor = connection.execute("SELECT * FROM jlc_components")
        total = 0
        while rows := cursor.fetchmany(BATCH_SIZE):
            for raw in rows:
                row = _row_dict(raw)
                total += 1
                category = _default_value(row.get("category"))
                subcategory = _default_value(row.get("subcategory"))
                localized_category = category_i18n.translate_primary(category, "zh")
                localized_subcategory = category_i18n.translate_secondary(subcategory, "zh")
                try:
                    attributes = json.loads(row.get("attributes") or "{}")
                except (TypeError, json.JSONDecodeError):
                    attributes = {}
                if not isinstance(attributes, dict):
                    attributes = {}
                specs = extract_jlcparts_specs(category, subcategory, attributes, row.get("description"))
                values = {
                    "image": "44 x 44",
                    "specs": specs,
                    "package": row.get("package"),
                    "mfr": row.get("mfr"),
                    "category": (category, localized_category, subcategory, localized_subcategory),
                    "manufacturer": row.get("manufacturer"),
                    "lcsc": f"C{row.get('lcsc', '')}",
                    "stock": row.get("stock"),
                    "price": _first_price(row.get("price")),
                    "actions": "Add Details",
                }
                for layout in layouts:
                    _observe(measurements, layout, values, source="jlcparts")
                part_name = _default_value(row.get("mfr"))
                inv_values = {
                    "name": part_name,
                    "source": "JLCPCB",
                    "package": row.get("package"),
                    "location": "Default Storage",
                    "warehouse": ("In Warehouse", "Not in Warehouse", "在库", "未入库"),
                    "quantity": (0, 999999),
                    "projects": "-",
                    "actions": "Details",
                    "id": 999999,
                }
                _observe(measurements, "inventory", inv_values, source="jlcparts")
                _observe(measurements, "search-inventory-overview", {
                    "id": 999999, "name": part_name, "package": row.get("package"),
                    "location": "Default Storage", "quantity": 999999, "actions": "Details",
                }, source="jlcparts")
                _feed_business_part(measurements, part_name, row.get("manufacturer"), row.get("package"), category,
                                    source="jlcparts")
                _observe(measurements, "bom-preview", {
                    "component": (part_name, row.get("manufacturer")),
                    "matched_part": (part_name, row.get("manufacturer"), row.get("package")),
                }, source="jlcparts")
        row_counts["jlcparts"] = total
        _record_source(measurements, str(path), total, (
            "jlcparts", "search-jlcparts-overview", "search-jlcparts-single", "inventory",
            "search-inventory-overview", "search-inventory-single", "project-bom", "project-shortage",
            "procurement", "bom-preview",
        ))
    finally:
        connection.close()


def _feed_business_part(measurements: dict[str, LayoutMeasurements], name: object,
                        manufacturer: object, package: object, part_type: object, *, source: str) -> None:
    common = {
        "part_name": name,
        "manufacturer": manufacturer,
        "package": package,
        "type": part_type,
        "available": (0, 999999),
        "needed": 999999,
        "shortage": 999999,
        "actions": "Edit Quantity Remove",
    }
    _observe(measurements, "project-bom", common, source=source)
    _observe(measurements, "project-shortage", common, source=source)
    _observe(measurements, "procurement", {
        "part_name": name, "package": package, "type": part_type,
        "available": 999999, "total_needed": 999999, "shortage": 999999,
    }, source=source)


def _scan_altium(path: Path, measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int]) -> None:
    if not path.exists():
        row_counts["altium"] = 0
        return
    from app.i18n.category_i18n import category_i18n

    connection = _connect_readonly(path)
    layouts = ("altium", "search-altium-overview")
    try:
        if not _table_exists(connection, "altium_components"):
            row_counts["altium"] = 0
            return
        cursor = connection.execute("SELECT * FROM altium_components")
        total = 0
        while rows := cursor.fetchmany(BATCH_SIZE):
            for raw in rows:
                row = _row_dict(raw)
                total += 1
                category = _default_value(row.get("category"))
                localized = category_i18n.translate_altium(category, "zh")
                values = {
                    "specs": _altium_specs(row),
                    "package": row.get("package"),
                    "lib_ref": row.get("lib_reference"),
                    "category": (category, localized),
                    "manufacturer": row.get("manufacturer"),
                    "lcsc_part": row.get("lcsc_part"),
                    "type": row.get("source_type"),
                    "actions": "Add Details",
                }
                for layout in layouts:
                    layout_values = dict(values)
                    if layout.startswith("search-"):
                        layout_values["specs"] = _altium_specs(row, 35)
                    _observe(measurements, layout, layout_values, source="altium")
                name = _default_value(row.get("lib_reference"))
                _observe(measurements, "inventory", {
                    "name": name, "source": "Altium", "package": row.get("package"),
                    "location": "Default Storage", "warehouse": ("In Warehouse", "Not in Warehouse"),
                    "quantity": (0, 999999), "projects": "-", "actions": "Details", "id": 999999,
                }, source="altium")
                _observe(measurements, "search-inventory-overview", {
                    "id": 999999, "name": name, "package": row.get("package"),
                    "location": "Default Storage", "quantity": 999999, "actions": "Details",
                }, source="altium")
                _feed_business_part(measurements, name, row.get("manufacturer"), row.get("package"), category,
                                    source="altium")
                _observe(measurements, "bom-preview", {
                    "component": (name, row.get("manufacturer")),
                    "matched_part": (name, row.get("manufacturer"), row.get("package")),
                }, source="altium")
        row_counts["altium"] = total
        _record_source(measurements, str(path), total, (
            "altium", "search-altium-overview", "search-altium-single", "inventory",
            "search-inventory-overview", "search-inventory-single", "project-bom", "project-shortage",
            "procurement", "bom-preview",
        ))
    finally:
        connection.close()


def _scan_kicad(path: Path, measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int]) -> None:
    if not path.exists():
        row_counts["kicad"] = 0
        return
    connection = _connect_readonly(path)
    layouts = ("kicad", "search-kicad-overview")
    try:
        if not _table_exists(connection, "kicad_symbols"):
            row_counts["kicad"] = 0
            return
        cursor = connection.execute("SELECT * FROM kicad_symbols")
        total = 0
        while rows := cursor.fetchmany(BATCH_SIZE):
            for raw in rows:
                row = _row_dict(raw)
                total += 1
                description = row.get("description") or row.get("keywords") or ""
                values = {
                    "name": row.get("name") or row.get("value"),
                    "library": row.get("library"), "reference": row.get("reference"),
                    "extends": row.get("extends"), "footprint": row.get("footprint"),
                    "description": description, "actions": "Add Details",
                }
                for layout in layouts:
                    if layout == "kicad":
                        _observe(measurements, layout, values, source="kicad")
                    else:
                        _observe(measurements, layout, {
                            "name": (values["name"], description),
                            "library": values["library"], "footprint": values["footprint"],
                            "actions": values["actions"],
                        }, source="kicad")
                name = _default_value(row.get("name") or row.get("value"))
                _observe(measurements, "inventory", {
                    "name": name, "source": "KiCad", "package": row.get("footprint"),
                    "location": "Default Storage", "warehouse": ("In Warehouse", "Not in Warehouse"),
                    "quantity": (0, 999999), "projects": "-", "actions": "Details", "id": 999999,
                }, source="kicad")
                _observe(measurements, "search-inventory-overview", {
                    "id": 999999, "name": name, "package": row.get("footprint"),
                    "location": "Default Storage", "quantity": 999999, "actions": "Details",
                }, source="kicad")
                _feed_business_part(measurements, name, "", row.get("footprint"), "KiCad", source="kicad")
                _observe(measurements, "bom-preview", {
                    "component": (name, description), "designator": row.get("reference"),
                    "footprint": row.get("footprint"), "matched_part": name,
                }, source="kicad")
        row_counts["kicad"] = total
        _record_source(measurements, str(path), total, (
            "kicad", "search-kicad-overview", "search-kicad-single", "inventory",
            "search-inventory-overview", "search-inventory-single", "project-bom", "project-shortage",
            "procurement", "bom-preview",
        ))
    finally:
        connection.close()


def _scan_fasteners(path: Path, measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int]) -> None:
    if not path.exists():
        row_counts["fasteners"] = 0
        return
    from app.i18n.fastener_aliases import localized_standard_name

    connection = _connect_readonly(path)
    layouts = ("fasteners", "search-fasteners-overview")
    try:
        if not _table_exists(connection, "fastener_standards"):
            row_counts["fasteners"] = 0
            return
        cursor = connection.execute("SELECT * FROM fastener_standards")
        total = 0
        while rows := cursor.fetchmany(BATCH_SIZE):
            for raw in rows:
                row = _row_dict(raw)
                total += 1
                code = row.get("standard_code")
                standard_name = row.get("standard_name")
                localized_name = localized_standard_name(str(code or ""), str(standard_name or ""), "zh")
                domain = row.get("domain") or "-"
                category = (row.get("category_group_zh"), row.get("category_group"))
                desc = (localized_name, standard_name, row.get("description"), row.get("param_table_name"))
                common = {
                    "code": code, "authority": row.get("authority"), "domain": domain,
                    "category": category, "description": desc,
                    "has_length": ("Multiple Lengths", "Single Part", "多长度系列", "单件/无长度"),
                    "actions": "Details",
                }
                for layout in layouts:
                    _observe(measurements, layout, common, source="fasteners")
                _observe(measurements, "inventory", {
                    "name": localized_name, "source": "Fasteners", "package": row.get("param_table_name"),
                    "location": "Default Storage", "warehouse": ("In Warehouse", "Not in Warehouse"),
                    "quantity": (0, 999999), "projects": "-", "actions": "Details", "id": 999999,
                }, source="fasteners")
                _observe(measurements, "search-inventory-overview", {
                    "id": 999999, "name": localized_name, "package": row.get("param_table_name"),
                    "location": "Default Storage", "quantity": 999999, "actions": "Details",
                }, source="fasteners")
                _feed_business_part(measurements, localized_name, row.get("authority"), row.get("param_table_name"), domain,
                                    source="fasteners")
                _observe(measurements, "bom-preview", {
                    "component": (localized_name, row.get("description")),
                    "matched_part": (localized_name, row.get("authority")),
                }, source="fasteners")
        row_counts["fasteners"] = total
        _record_source(measurements, str(path), total, (
            "fasteners", "search-fasteners-overview", "search-fasteners-single", "inventory",
            "search-inventory-overview", "search-inventory-single", "project-bom", "project-shortage",
            "procurement", "bom-preview",
        ))
    finally:
        connection.close()


def _resolve_main_db(explicit: Path | None) -> Path | None:
    if explicit:
        return explicit.resolve()
    raw_url = os.getenv("DATABASE_URL")
    env_file = ROOT / ".env"
    if not raw_url and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "DATABASE_URL":
                raw_url = value.strip().strip("\"'")
                break
    raw_url = raw_url or "sqlite:///./partshelf.db"
    if not raw_url.startswith("sqlite:"):
        raise ValueError("The width generator reads SQLite databases. Pass --main-db for a SQLite export.")
    path_text = raw_url.removeprefix("sqlite:///")
    path = Path(path_text)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _scan_main_database(path: Path | None, measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int]) -> None:
    if path is None or not path.exists():
        row_counts["main_database"] = 0
        return
    connection = _connect_readonly(path)
    try:
        if _table_exists(connection, "projects"):
            total = 0
            for raw in connection.execute("SELECT name, description FROM projects"):
                row = _row_dict(raw)
                total += 1
                _observe(measurements, "projects", {
                    "id": 999999, "name": row.get("name"), "description": row.get("description"),
                    "parts_count": 999999, "actions": "Details Delete",
                }, source="main_database.projects")
                _observe(measurements, "procurement", {"projects": row.get("name")}, source="main_database.projects")
                _observe(measurements, "inventory", {"projects": row.get("name")}, source="main_database.projects")
            row_counts["projects"] = total
            _record_source(measurements, "main_database.projects", total, ("projects", "procurement", "inventory"))
        else:
            row_counts["projects"] = 0
        for table, query, layouts in (
            ("parts", "SELECT parts.storage_location, parts.note, inventories.quantity_available FROM parts LEFT JOIN inventories ON inventories.part_id = parts.id", ("inventory",)),
            ("project_parts", "SELECT quantity_needed FROM project_parts", ("project-bom", "project-shortage", "procurement")),
        ):
            if not _table_exists(connection, table):
                continue
            total = 0
            for raw in connection.execute(query):
                row = _row_dict(raw)
                total += 1
                if table == "parts":
                    _observe(measurements, "inventory", {
                        "location": row.get("storage_location"), "warehouse": ("In Warehouse", "Not in Warehouse"),
                        "quantity": row.get("quantity_available"), "name": row.get("note"),
                    }, source="main_database.parts")
                else:
                    for layout in layouts:
                        _observe(measurements, layout, {
                            "needed": row.get("quantity_needed"), "total_needed": row.get("quantity_needed"),
                        }, source="main_database.project_parts")
            row_counts[table] = total
            source = f"main_database.{table}"
            targets = ("inventory",) if table == "parts" else ("project-bom", "project-shortage", "procurement")
            _record_source(measurements, source, total, targets)
    finally:
        connection.close()


def _scan_bom_samples(paths: Sequence[Path], measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int]) -> None:
    total = 0
    if paths:
        from app.services.bom_service import parse_bom_file

        for path in paths:
            if not path.exists():
                continue
            rows = parse_bom_file(path.read_bytes(), path.name)
            file_total = 0
            for row in rows:
                total += 1
                file_total += 1
                component = tuple(row.get(key) for key in ("value", "comment", "manufacturer_part", "manufacturer"))
                _observe(measurements, "bom-preview", {
                    "select": "Select", "row": row.get("row_index"), "component": component,
                    "designator": row.get("designator"), "footprint": row.get("footprint"),
                    "quantity": row.get("quantity"), "match_status": ("In Inventory", "Library Match", "Review Required", "Unmatched"),
                    "matched_part": component,
                }, source=f"bom_sample:{path.name}")
            row_counts[f"bom_sample:{path}"] = file_total
            _record_source(measurements, f"bom_sample:{path.name}", file_total, ("bom-preview",))
    row_counts["bom_samples"] = total


def collect_measurements(main_db: Path | None, libraries_dir: Path, bom_samples: Sequence[Path]) -> tuple[dict[str, LayoutMeasurements], dict[str, int], dict[str, object]]:
    measurements = {name: LayoutMeasurements.for_layout(spec) for name, spec in LAYOUTS.items()}
    shared_layouts = (
        ("search-jlcparts-overview", "jlcparts"),
        ("search-jlcparts-single", "jlcparts"),
        ("search-altium-single", "search-altium-overview"),
        ("search-kicad-single", "search-kicad-overview"),
        ("search-fasteners-single", "search-fasteners-overview"),
        ("search-inventory-single", "search-inventory-overview"),
    )
    for alias, source in shared_layouts:
        measurements[alias].columns = measurements[source].columns
        for column in LAYOUTS[alias].columns:
            measurements[alias].columns.setdefault(column.name, WidthHistogram())
    row_counts: dict[str, int] = {}
    _scan_jlc(libraries_dir / "jlcparts.db", measurements, row_counts)
    _scan_altium(libraries_dir / "altium_library.db", measurements, row_counts)
    _scan_kicad(libraries_dir / "kicad_symbols.db", measurements, row_counts)
    _scan_fasteners(libraries_dir / "fasteners.db", measurements, row_counts)
    _scan_main_database(main_db, measurements, row_counts)
    _scan_bom_samples(bom_samples, measurements, row_counts)
    source_files: dict[str, object] = {
        "main_database": {
            "path": str(main_db) if main_db else None,
            "available": bool(main_db and main_db.exists()),
            "rows": row_counts.get("parts", 0) + row_counts.get("projects", 0) + row_counts.get("project_parts", 0),
        },
    }
    for name, filename in (
        ("jlcparts", "jlcparts.db"),
        ("altium", "altium_library.db"),
        ("kicad", "kicad_symbols.db"),
        ("fasteners", "fasteners.db"),
    ):
        path = libraries_dir / filename
        source_files[name] = {
            "path": str(path), "available": path.exists(), "rows": row_counts.get(name, 0),
        }
    source_files["bom_samples"] = [
        {
            "path": str(path), "available": path.exists(),
            "rows": row_counts.get(f"bom_sample:{path}", 0),
        }
        for path in bom_samples
    ]
    return measurements, row_counts, source_files


def _measure_layout(spec: LayoutSpec, result: LayoutMeasurements, catalogs: dict) -> tuple[list[ColumnMeasurements], list[int]]:
    columns: list[ColumnMeasurements] = []
    for column in spec.columns:
        hist = result.columns[column.name]
        header_width = max(
            estimate_text_width(_translate_header(catalogs, column, language))
            for language in ("zh", "en")
        ) + 24
        columns.append(ColumnMeasurements(
            column.name,
            header_width,
            column.control_px,
            hist.quantile(0.50),
            hist.quantile(0.95),
            hist.quantile(0.99),
            column.first_text,
            column.max_width,
            column.fallback_px,
        ))
    widths = choose_column_widths(columns, spec.budget_px)
    return columns, widths


def build_report(measurements: dict[str, LayoutMeasurements], row_counts: dict[str, int], source_files: dict[str, object] | None = None) -> dict:
    catalogs = _read_catalogs()
    report = {"sources": row_counts, "source_files": source_files or {}, "layouts": {}}
    for name, spec in LAYOUTS.items():
        result = measurements[name]
        measured, widths = _measure_layout(spec, result, catalogs)
        report["layouts"][name] = {
            "template": spec.template,
            "css": spec.css_file,
            "rows": result.sources,
            "width_sum_px": sum(widths),
            "columns": [
                {
                    "name": spec_col.name,
                    "observations": result.columns[spec_col.name].count,
                    "sources": result.columns[spec_col.name].sources,
                    "p50_chars": result.columns[spec_col.name].quantile_chars(0.50),
                    "p95_chars": result.columns[spec_col.name].quantile_chars(0.95),
                    "p99_chars": result.columns[spec_col.name].quantile_chars(0.99),
                    "p50_px": result.columns[spec_col.name].quantile(0.50),
                    "p95_px": result.columns[spec_col.name].quantile(0.95),
                    "p99_px": result.columns[spec_col.name].quantile(0.99),
                    "header_px": measured[spec.columns.index(spec_col)].header_width,
                    "natural_floor_px": max(
                        measured[spec.columns.index(spec_col)].header_width,
                        measured[spec.columns.index(spec_col)].control_width,
                        measured[spec.columns.index(spec_col)].median_width,
                        measured[spec.columns.index(spec_col)].fallback_width,
                    ),
                    "selected_px": width,
                    "priority": "first_text" if spec_col.first_text else "equal",
                }
                for spec_col, width in zip(spec.columns, widths)
            ],
        }
    return report


def render_css(layouts: Iterable[tuple[LayoutSpec, list[int]]]) -> str:
    rules = [CSS_START]
    for spec, widths in layouts:
        total = sum(widths)
        selector = f'table[data-list-layout="{spec.name}"]'
        rules.append(f"{selector} {{ table-layout: fixed; width: max(100%, {total}px); min-width: {total}px; }}")
        rules.append(f"{selector} td {{ white-space: normal; overflow-wrap: anywhere; }}")
        rules.append(f"{selector} .text-truncate {{ max-width: none !important; overflow: visible; text-overflow: clip; white-space: normal; }}")
        rules.append(f"{selector} .d-flex, {selector} .d-inline-flex {{ flex-wrap: wrap; min-width: 0; }}")
        for index, width in enumerate(widths, start=1):
            rules.append(f"{selector} th:nth-child({index}), {selector} td:nth-child({index}) {{ width: {width}px; min-width: {width}px; }}")
        rules.append("")
    rules.append(CSS_END)
    return "\n".join(rules) + "\n"


def _replace_generated_block(existing: str, generated: str) -> str:
    pattern = re.compile(re.escape(CSS_START) + r".*?" + re.escape(CSS_END), re.DOTALL)
    if pattern.search(existing):
        return pattern.sub(generated.strip(), existing)
    return existing.rstrip() + "\n\n" + generated


def _remove_width_style(tag: str) -> str:
    style_match = re.search(r'\sstyle="([^"]*)"', tag)
    if not style_match:
        return tag
    declarations = [part.strip() for part in style_match.group(1).split(";") if part.strip()]
    kept = [item for item in declarations if not re.match(r"(?:min-width|width)\s*:", item, re.IGNORECASE)]
    if kept:
        return tag[:style_match.start(1)] + "; ".join(kept) + tag[style_match.end(1):]
    return tag[:style_match.start()] + tag[style_match.end():]


def install_markup_bindings() -> None:
    template_bindings = [
        ("inventory.html", "parts-table-body", "inventory", "inventory.css"),
        ("libraries_jlcparts.html", "tableBody", "jlcparts", "libraries_jlcparts.css"),
        ("libraries_altium.html", "tableBody", "altium", "libraries_altium.css"),
        ("libraries_kicad.html", "tableBody", "kicad", "libraries_kicad.css"),
        ("libraries_fasteners.html", "tableBody", "fasteners", "libraries_fasteners.css"),
        ("search.html", "overview-inventory-body", "search-inventory-overview", "search.css"),
        ("search.html", "overview-jlcparts-body", "search-jlcparts-overview", "search.css"),
        ("search.html", "overview-altium-body", "search-altium-overview", "search.css"),
        ("search.html", "overview-kicad-body", "search-kicad-overview", "search.css"),
        ("search.html", "overview-fasteners-body", "search-fasteners-overview", "search.css"),
        ("search.html", "singleTableBody", "search-inventory-single", "search.css"),
        ("projects.html", "projects-table-body", "projects", "projects.css"),
        ("project_details.html", "bom-table-body", "project-bom", "project_details.css"),
        ("project_details.html", "shortage-table-body", "project-shortage", "project_details.css"),
        ("procurement.html", "procurement-table-body", "procurement", "procurement.css"),
        ("bom_import.html", "bomPreviewTable", "bom-preview", "bom_import.css"),
    ]
    template_files = {name for name, *_ in template_bindings}
    for template_name in template_files:
        path = ROOT / "templates" / template_name
        original = path.read_bytes().decode("utf-8")
        newline = "\r\n" if "\r\n" in original else "\n"
        text = original
        relevant = [(marker, layout) for file_name, marker, layout, _ in template_bindings if file_name == template_name]
        for marker, layout in relevant:
            matches = list(re.finditer(r"<table\b[^>]*>[\s\S]*?</table>", text, re.IGNORECASE))
            candidates = [match for match in matches if marker in match.group(0)]
            if len(candidates) != 1:
                raise RuntimeError(f"Expected one table containing {marker!r} in {path}, found {len(candidates)}")
            match = candidates[0]
            block = match.group(0)
            open_tag = re.search(r"<table\b[^>]*>", block, re.IGNORECASE)
            assert open_tag
            tag = open_tag.group(0)
            if re.search(r'\bdata-list-layout="[^"]*"', tag):
                tag = re.sub(r'\bdata-list-layout="[^"]*"', f'data-list-layout="{layout}"', tag)
            else:
                tag = tag[:-1] + f' data-list-layout="{layout}">'
            block = block[:open_tag.start()] + tag + block[open_tag.end():]
            block = re.sub(r"<th\b[^>]*>", lambda found: _remove_width_style(found.group(0)), block, flags=re.IGNORECASE)
            text = text[:match.start()] + block + text[match.end():]
        for _, _, _, css_name in [item for item in template_bindings if item[0] == template_name]:
            css_link = f'<link href="/static/css/{css_name}" rel="stylesheet">'
            if css_link not in text:
                text = text.replace("</head>", f"    {css_link}{newline}  </head>", 1)
        path.write_text(text, encoding="utf-8")

    inventory_js = ROOT / "static" / "js" / "inventory.js"
    inventory_text = inventory_js.read_bytes().decode("utf-8")
    old_note_markup = 'class="d-block text-muted text-truncate" style="max-width: 250px;"'
    new_note_markup = 'class="d-block text-muted inventory-note"'
    if old_note_markup in inventory_text:
        inventory_text = inventory_text.replace(old_note_markup, new_note_markup)
        inventory_js.write_text(inventory_text, encoding="utf-8")
    elif new_note_markup not in inventory_text:
        raise RuntimeError(f"Could not find the inventory note cell in {inventory_js}")

    search_js = ROOT / "static" / "js" / "search.js"
    original_js = search_js.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in original_js else "\n"
    js = original_js
    js = re.sub(r"<th\b[^>]*>", lambda found: _remove_width_style(found.group(0)), js, flags=re.IGNORECASE)
    binding = "document.getElementById('singleViewTable').dataset.listLayout = `search-${activeTab}-single`;"
    if binding not in js:
        if SINGLE_SEARCH_ANCHOR not in js:
            raise RuntimeError(f"Could not find the single-search binding point in {search_js}")
        js = js.replace(SINGLE_SEARCH_ANCHOR, f"{binding}{newline}        {SINGLE_SEARCH_ANCHOR}", 1)
    search_js.write_text(js, encoding="utf-8")


def write_css(report: dict) -> None:
    by_page: dict[str, list[tuple[LayoutSpec, list[int]]]] = {}
    for name, spec in LAYOUTS.items():
        widths = [column["selected_px"] for column in report["layouts"][name]["columns"]]
        by_page.setdefault(spec.css_file, []).append((spec, widths))
    for css_name, layouts in by_page.items():
        path = ROOT / "static" / "css" / css_name
        existing = path.read_bytes().decode("utf-8") if path.exists() else ""
        generated = render_css(layouts)
        path.write_text(_replace_generated_block(existing, generated), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true", help="Print measured widths as JSON without writing files")
    mode.add_argument("--write", action="store_true", help="Generate per-page CSS and install table bindings")
    parser.add_argument("--main-db", type=Path, help="Path to the SQLite PartShelf database")
    parser.add_argument("--libraries-dir", type=Path, default=ROOT / "data" / "libraries")
    parser.add_argument("--bom-sample", type=Path, nargs="*", default=[], help="Optional CSV/XLSX BOM samples")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    main_db = _resolve_main_db(args.main_db)
    measurements, row_counts, source_files = collect_measurements(main_db, args.libraries_dir.resolve(), args.bom_sample)
    report = build_report(measurements, row_counts, source_files)
    rendered_report = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered_report + "\n", encoding="utf-8")
    if args.report:
        print(rendered_report)
    if args.write:
        write_css(report)
        install_markup_bindings()
        print(f"Updated generated table widths for {len(LAYOUTS)} layouts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
