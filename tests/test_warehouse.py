import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_warehouse_page_is_available_from_the_navigation():
    response = client.get("/warehouse?lang=en")

    assert response.status_code == 200
    assert 'href="/warehouse"' in response.text
    assert 'id="warehouse-page"' in response.text


def test_warehouse_boxes_and_drawer_labels_have_stable_scaled_configuration():
    response = client.get("/warehouse?lang=en")
    match = re.search(
        r'<script id="warehouse-cabinet-config" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )

    assert response.status_code == 200
    assert match
    cabinets = json.loads(match.group(1))
    en_warehouse_translations = json.loads(
        (Path(__file__).resolve().parents[1] / "app" / "i18n" / "locales" / "en.json").read_text(encoding="utf-8")
    )["warehouse"]
    assert [cabinet["displayNumber"] for cabinet in cabinets] == [0, 1, 2]
    assert [cabinet["id"] for cabinet in cabinets] == ["BOX-000", "BOX-001", "BOX-002"]

    all_payloads = []
    for cabinet in cabinets:
        assert (cabinet["widthMm"], cabinet["depthMm"], cabinet["heightMm"]) == (395, 160, 485)
        groups = cabinet["drawerGroups"]
        assert [(group["typeCode"], group["rows"], group["columns"]) for group in groups] == [
            ("S", 5, 6),
            ("L", 3, 3),
        ]
        assert [(group["drawerWidthMm"], group["drawerHeightMm"], group["drawerDepthMm"]) for group in groups] == [
            (50, 36, 140),
            (110, 60, 140),
        ]
        assert len(groups[0]["drawers"]) == 30
        assert len(groups[1]["drawers"]) == 9

        for group in groups:
            assert group["typeLabelKey"] in en_warehouse_translations
            for index, drawer in enumerate(group["drawers"], start=1):
                row = (index - 1) // group["columns"] + 1
                column = (index - 1) % group["columns"] + 1
                assert drawer["row"] == row
                assert drawer["column"] == column
                assert drawer["code"] == f"{group['typeCode']}-{index:02}"
                assert drawer["qrPayload"] == f"PARTSHELF-WH:{cabinet['id']}:{drawer['code']}"
                assert drawer["xMm"] == group["xMm"] + (column - 1) * (group["drawerWidthMm"] + group["gapMm"])
                assert drawer["yMm"] == group["yMm"] + (row - 1) * (group["drawerHeightMm"] + group["gapMm"])
                all_payloads.append(drawer["qrPayload"])

    assert len(all_payloads) == 117
    assert len(set(all_payloads)) == 117


def test_warehouse_page_exposes_local_qr_controls_and_a4_print_resources():
    response = client.get("/warehouse?lang=en")
    translations_match = re.search(
        r'<script id="page-translations" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )

    assert response.status_code == 200
    assert '<select id="warehouse-cabinet-select"' in response.text
    assert 'id="warehouse-print-button"' in response.text
    assert 'id="warehouse-drawer-details"' in response.text
    assert "/static/js/vendor/qrcode-generator.js" in response.text
    assert "/static/js/warehouse.js" in response.text
    assert not re.search(r'<script[^>]+src=["\']https?://', response.text)
    assert translations_match
    translations = json.loads(translations_match.group(1))
    assert translations["print_labels"] == "Print labels for this box"

    stylesheet = client.get("/static/css/warehouse.css")
    assert stylesheet.status_code == 200
    assert "@page" in stylesheet.text
    assert "A4" in stylesheet.text
    assert "max-width: 51rem" in stylesheet.text
    assert "max-width: 34rem" not in stylesheet.text
    assert "46mm" in stylesheet.text
    assert "32mm" in stylesheet.text
    assert "grid-template-columns: repeat(4, 46mm)" in stylesheet.text
    assert "grid-template-rows: repeat(8, 32mm)" in stylesheet.text
    assert 4 * 46 + 3 * 2 == 190
    assert 8 * 32 + 7 * 2 <= 297 - 20

    qr_library = client.get("/static/js/vendor/qrcode-generator.js")
    page_script = client.get("/static/js/warehouse.js")
    assert qr_library.status_code == 200
    assert page_script.status_code == 200
    assert "createSvgTag" in qr_library.text
    assert "warehouse-cabinet-config" in page_script.text
    assert '"font-size": Math.min(15, drawer.heightMm * 0.4, drawer.widthMm * 0.25)' in page_script.text
    assert "const labelsPerPage = 32" in page_script.text
    assert "fetch(" not in page_script.text
    assert "/api/" not in page_script.text


def test_warehouse_translations_are_available_in_both_languages():
    english = client.get("/warehouse?lang=en")
    chinese = client.get("/warehouse?lang=zh")

    assert "<h1>Parts Warehouse</h1>" in english.text
    assert "<h1>仓储箱</h1>" in chinese.text
