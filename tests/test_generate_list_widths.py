import sqlite3

from scripts.generate_list_widths import (
    ColumnMeasurements,
    LAYOUTS,
    LayoutMeasurements,
    _remove_width_style,
    build_report,
    choose_column_widths,
    estimate_text_width,
    render_css,
    collect_measurements,
)


def test_width_estimation_accounts_for_cjk_and_combining_marks():
    assert estimate_text_width("型号") > estimate_text_width("AB")
    assert estimate_text_width("e\u0301") == estimate_text_width("e")
    assert estimate_text_width(0) == estimate_text_width("0")


def test_width_distribution_preserves_short_cells_and_prioritizes_first_text_column():
    columns = [
        ColumnMeasurements("image", 30, 48, 48, 48, 48),
        ColumnMeasurements("name", 56, 0, 90, 180, 280, first_text=True, max_width=280),
        ColumnMeasurements("package", 60, 0, 44, 100, 130, max_width=220),
        ColumnMeasurements("actions", 54, 152, 152, 152, 152),
    ]

    widths = choose_column_widths(columns, budget_px=580)

    assert widths[0] == 48
    assert widths[1] == 280
    assert widths[2] >= 100
    assert widths[3] == 152
    assert sum(widths) >= 420


def test_layout_manifest_covers_all_business_lists_and_search_modes():
    expected = {
        "inventory", "jlcparts", "altium", "kicad", "fasteners",
        "search-inventory-overview", "search-jlcparts-overview",
        "search-altium-overview", "search-kicad-overview",
        "search-fasteners-overview", "search-inventory-single",
        "search-jlcparts-single", "search-altium-single",
        "search-kicad-single", "search-fasteners-single", "projects",
        "project-bom", "project-shortage", "procurement", "bom-preview",
    }

    assert expected <= set(LAYOUTS)
    assert all(layout.columns for layout in LAYOUTS.values())


def test_report_exposes_missing_sources_and_character_and_pixel_quantiles():
    measurements = {name: LayoutMeasurements.for_layout(layout) for name, layout in LAYOUTS.items()}
    report = build_report(
        measurements,
        {"projects": 0, "parts": 0, "project_parts": 0, "bom_samples": 0},
        {"main_database": {"available": True, "rows": 0}},
    )

    assert report["source_files"]["main_database"]["rows"] == 0
    column = report["layouts"]["bom-preview"]["columns"][2]
    assert {"p50_chars", "p95_chars", "p99_chars", "p95_px", "selected_px"} <= set(column)


def test_report_records_each_column_data_source():
    measurements = {name: LayoutMeasurements.for_layout(layout) for name, layout in LAYOUTS.items()}
    measurements["inventory"].observe("name", "resistor", source="main_database.parts")

    report = build_report(measurements, {})
    column = next(item for item in report["layouts"]["inventory"]["columns"] if item["name"] == "name")

    assert column["sources"] == {"main_database.parts": 1}


def test_fastener_single_search_widths_include_length_badge_data(tmp_path):
    libraries = tmp_path / "libraries"
    libraries.mkdir()
    connection = sqlite3.connect(libraries / "fasteners.db")
    connection.execute(
        """CREATE TABLE fastener_standards (
            standard_code TEXT,
            authority TEXT,
            domain TEXT,
            category_group TEXT,
            category_group_zh TEXT,
            standard_name TEXT,
            description TEXT,
            param_table_name TEXT
        )"""
    )
    connection.execute(
        "INSERT INTO fastener_standards VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ISO 4762", "ISO", "Mechanical", "Screws", "螺钉", "Socket Head Cap Screw", "A long description", "M3"),
    )
    connection.commit()
    connection.close()

    measurements, _, _ = collect_measurements(None, libraries, [])

    assert measurements["search-fasteners-single"].columns["has_length"].count == 1


def test_markup_cleanup_keeps_non_width_styles_and_generated_css_wraps_content():
    tag = _remove_width_style('<th style="width: 120px; color: red; max-width: 240px;">')
    assert tag == '<th style="color: red; max-width: 240px">'

    css = render_css([(LAYOUTS["bom-preview"], [70, 80, 300, 180, 220, 90, 160, 320])])
    assert "overflow-wrap: anywhere" in css
    assert "min-width: 1420px" in css
