import re
import sqlite3
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.i18n.category_i18n import category_i18n, CATEGORIES_DIR
from app.services.external_library_service import (
    ALTIUM_DB_PATH,
    JLCPARTS_DB_PATH,
    resolve_part_full,
    resolve_part_summary,
)
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.project import Project
from app.models.project_part import ProjectPart
from db.database import Base, get_db

client = TestClient(app)


def test_category_files_exist_and_no_emoji():
    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
    )
    file_path = CATEGORIES_DIR / "zh.json"
    assert file_path.exists()
    assert not (CATEGORIES_DIR / "en.json").exists()
    assert not emoji_pattern.search(file_path.read_text(encoding="utf-8"))


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

    assert category_i18n.translate_primary("Others", "zh") == "其他"
    assert category_i18n.translate_secondary("Others", "zh") == "其他元件"
    assert category_i18n.translate_primary("Global Sourcing Parts", "zh") == "全球采购元器件"
    assert category_i18n.translate_secondary("Global Sourcing Parts", "zh") == "全球采购物料"
    assert category_i18n.translate_secondary("NonExistentCategoryName123", "zh") == "NonExistentCategoryName123"
    assert category_i18n.translate_primary("Sensors", "fr") == "传感器"


def test_api_category_translations():
    res = client.get("/api/libraries/category-translations?lang=zh")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert set(data) == {"altium", "primary", "secondary"}
    assert data["altium"]["Capacitors - MLCC"] == "多层陶瓷电容器 (MLCC)"
    assert data["secondary"]["Audio Amplifiers"] == "音频功率放大器"
    assert data["primary"]["Others"] != data["secondary"]["Others"]
    assert client.get("/api/libraries/category-translations?lang=en").json() == {
        "altium": {}, "primary": {}, "secondary": {}
    }


def test_chinese_category_catalog_covers_imported_libraries():
    catalog = category_i18n.get_all()
    with sqlite3.connect(f"file:{ALTIUM_DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        altium = {row[0] for row in conn.execute("SELECT DISTINCT category FROM altium_components WHERE category != ''")}
    with sqlite3.connect(f"file:{JLCPARTS_DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        primary = {row[0] for row in conn.execute("SELECT DISTINCT category FROM jlc_components WHERE category != ''")}
        secondary = {row[0] for row in conn.execute("SELECT DISTINCT subcategory FROM jlc_components WHERE subcategory != ''")}
    for section, names in (("altium", altium), ("primary", primary), ("secondary", secondary)):
        assert names
        assert not names - set(catalog[section]), f"Untranslated {section} categories: {sorted(names - set(catalog[section]))}"


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


def test_api_english_locale_for_categories_lists_and_details():
    altium_categories = client.get("/api/libraries/altium/categories?lang=en").json()
    assert altium_categories
    assert all(row["category_localized"] == row["category"] for row in altium_categories)
    assert any(row["category"] == "Capacitors - MLCC" for row in altium_categories)

    altium = client.get("/api/libraries/altium?category=Capacitors%20-%20MLCC&page_size=1&lang=en").json()["items"][0]
    assert altium["category_localized"] == altium["category"]
    altium_detail = client.get(f"/api/libraries/altium/{altium['id']}?lang=en").json()
    assert altium_detail["category_localized"] == altium_detail["category"]

    jlc_categories = client.get("/api/libraries/jlcparts/categories?lang=en").json()
    assert jlc_categories
    assert all(row["category_localized"] == row["category"] for row in jlc_categories)
    assert all(sub["subcategory_localized"] == sub["subcategory"] for row in jlc_categories for sub in row["subcategories"])

    jlc = client.get("/api/libraries/jlcparts?category=Circuit%20Protection&page_size=1&lang=en").json()["items"][0]
    assert jlc["category_localized"] == jlc["category"]
    assert jlc["subcategory_localized"] == jlc["subcategory"]
    jlc_detail = client.get(f"/api/libraries/jlcparts/{jlc['lcsc']}?lang=en").json()
    assert jlc_detail["category_localized"] == jlc_detail["category"]
    assert jlc_detail["subcategory_localized"] == jlc_detail["subcategory"]


def test_api_language_cookie_and_query_override():
    with TestClient(app) as locale_client:
        page = locale_client.get("/libraries/altium?lang=en")
        assert page.status_code == 200
        response = locale_client.get("/api/libraries/altium?category=Capacitors%20-%20MLCC&page_size=1")
        item = response.json()["items"][0]
        assert item["category_localized"] == item["category"]
        response = locale_client.get("/api/libraries/altium?category=Capacitors%20-%20MLCC&page_size=1&lang=zh")
        assert response.json()["items"][0]["category_localized"] == "多层陶瓷电容器 (MLCC)"


def test_unified_search_uses_requested_language():
    result = client.get("/api/libraries/search?q=0603&target=altium&limit=2&lang=en").json()
    assert result["altium"]["items"]
    assert all(item["category_localized"] == item["category"] for item in result["altium"]["items"])


def test_inventory_summary_cache_and_external_details_follow_language():
    altium_id = client.get("/api/libraries/altium?category=Capacitors%20-%20MLCC&page_size=1").json()["items"][0]["id"]
    zh_summary = resolve_part_summary("altium", str(altium_id), lang="zh")
    en_summary = resolve_part_summary("altium", str(altium_id), lang="en")
    assert zh_summary["part_type"] == "多层陶瓷电容器 (MLCC)"
    assert en_summary["part_type"] == "Capacitors - MLCC"
    assert resolve_part_summary("altium", str(altium_id), lang="zh")["part_type"] == zh_summary["part_type"]
    assert resolve_part_full("altium", str(altium_id), lang="en")["external_details"]["category_localized"] == "Capacitors - MLCC"


def test_inventory_and_project_apis_localize_category_without_touching_main_database():
    altium_id = client.get("/api/libraries/altium?category=Capacitors%20-%20MLCC&page_size=1").json()["items"][0]["id"]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        part = Part(library_source="altium", external_part_id=str(altium_id))
        project = Project(name="Category locale test")
        db.add_all([part, project])
        db.flush()
        db.add_all([Inventory(part_id=part.id, quantity_available=1), ProjectPart(project_id=project.id, part_id=part.id)])
        db.commit()
        part_id, project_id = part.id, project.id

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as locale_client:
            inventory = locale_client.get("/api/inventory/get_parts_inventory?lang=en").json()
            assert inventory[0]["part_type"] == "Capacitors - MLCC"
            details = locale_client.get(f"/api/inventory/get_part_by_id?part_id={part_id}&lang=en").json()
            assert details["part_type"] == "Capacitors - MLCC"
            assert details["external_details"]["category_localized"] == "Capacitors - MLCC"
            project_parts = locale_client.get(f"/api/projects/{project_id}?lang=en").json()["parts"]
            assert project_parts[0]["part_type"] == "Capacitors - MLCC"
            procurement = locale_client.get("/api/projects/procurement/list?lang=en").json()
            assert procurement[0]["part_type"] == "Capacitors - MLCC"
            zh_inventory = locale_client.get("/api/inventory/get_parts_inventory?lang=zh").json()
            assert zh_inventory[0]["part_type"] == "多层陶瓷电容器 (MLCC)"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_web_templates_do_not_embed_full_category_catalog():
    for page in ("/libraries/jlcparts", "/libraries/altium", "/libraries/altium/1"):
        res = client.get(page)
        assert res.status_code == 200
        assert 'id="category-translations"' not in res.text
