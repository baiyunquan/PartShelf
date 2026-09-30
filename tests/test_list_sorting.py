from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_every_list_page_loads_shared_sorting_assets():
    templates = (
        "inventory.html",
        "libraries_jlcparts.html",
        "libraries_altium.html",
        "libraries_kicad.html",
        "libraries_fasteners.html",
        "search.html",
        "projects.html",
        "project_details.html",
        "procurement.html",
        "bom_import.html",
    )

    for name in templates:
        source = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert '/static/css/list_sorting.css' in source, name
        assert '/static/js/list_sorting.js' in source, name
        assert 'data-list-layout="' in source, name


def test_non_data_columns_are_explicitly_marked_as_not_sortable():
    templates = (
        "libraries_jlcparts.html",
        "search.html",
        "bom_import.html",
    )

    for name in templates:
        source = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert 'data-sortable="false"' in source, name


def test_dynamic_search_headers_exclude_images_and_actions():
    source = (ROOT / "static" / "js" / "search.js").read_text(encoding="utf-8")

    assert '<th data-sortable="false">${I18N.th_image' in source
    assert source.count('<th class="text-end" data-sortable="false">${I18N.th_actions') == 5


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_sorting_behavior_unit_suite():
    result = subprocess.run(
        ["node", "--test", "tests/js/list_sorting.test.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
