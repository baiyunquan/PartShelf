import re
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.i18n.category_i18n import category_i18n, CATEGORIES_DIR

client = TestClient(app)


def test_category_files_exist_and_no_emoji():
    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
    )
    for lang in ("zh", "en"):
        file_path = CATEGORIES_DIR / f"{lang}.json"
        assert file_path.exists(), f"File {file_path} must exist"
        content = file_path.read_text(encoding="utf-8")
        assert not emoji_pattern.search(content), f"No emojis allowed in {file_path}"


def test_category_i18n_translations():
    # Altium
    assert category_i18n.translate_altium("Capacitors - MLCC", "zh") == "多层陶瓷电容器 (MLCC)"
    assert category_i18n.translate_altium("Capacitors - MLCC", "en") == "Capacitors - MLCC"
    assert category_i18n.translate_altium("Resistors", "zh") == "电阻器"

    # JLCParts Primary
    assert category_i18n.translate_primary("Sensors", "zh") == "传感器"
    assert category_i18n.translate_primary("Sensors", "en") == "Sensors"
    assert category_i18n.translate_primary("Power Management (PMIC)", "zh") == "电源管理芯片 (PMIC)"

    # JLCParts Secondary
    assert category_i18n.translate_secondary("Audio Amplifiers", "zh") == "音频功率放大器"
    assert category_i18n.translate_secondary("Audio Amplifiers", "en") == "Audio Amplifiers"
    assert category_i18n.translate_secondary("Operational Amplifiers", "zh") == "运算放大器"

    # Fallback
    assert category_i18n.translate("NonExistentCategoryName123", "zh") == "NonExistentCategoryName123"


def test_api_category_translations():
    res = client.get("/api/libraries/category-translations?lang=zh")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert len(data) >= 500
    assert data["Capacitors - MLCC"] == "多层陶瓷电容器 (MLCC)"
    assert data["Audio Amplifiers"] == "音频功率放大器"


def test_api_jlcparts_categories_localized():
    res = client.get("/api/libraries/jlcparts/categories")
    assert res.status_code == 200
    categories = res.json()
    assert len(categories) > 0
    first = categories[0]
    assert "category" in first
    assert "category_localized" in first
    assert isinstance(first["subcategories"], list)
    if first["subcategories"]:
        assert "subcategory" in first["subcategories"][0]
        assert "subcategory_localized" in first["subcategories"][0]


def test_api_parts_category_localized():
    # JLCParts search
    res_jlc = client.get("/api/libraries/jlcparts?page_size=2")
    assert res_jlc.status_code == 200
    jlc_items = res_jlc.json()["items"]
    if jlc_items:
        assert "category_localized" in jlc_items[0]
        assert "subcategory_localized" in jlc_items[0]

    # Altium search
    res_altium = client.get("/api/libraries/altium?page_size=2")
    assert res_altium.status_code == 200
    altium_items = res_altium.json()["items"]
    if altium_items:
        assert "category_localized" in altium_items[0]


def test_web_templates_contain_category_translations():
    for page in ("/libraries/jlcparts", "/libraries/altium"):
        res = client.get(page)
        assert res.status_code == 200
        assert 'id="category-translations"' in res.text
