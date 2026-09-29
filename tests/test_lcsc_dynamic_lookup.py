"""On-demand LCSC lookup should fill exact local catalog misses."""

import json
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import external_library_service as libraries
from app.services import lcsc_dynamic_service as dynamic


@pytest.fixture
def jlc_library(tmp_path, monkeypatch):
    path = tmp_path / "jlcparts.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jlc_components (
            lcsc INTEGER PRIMARY KEY NOT NULL, fetched_at INTEGER NOT NULL,
            present INTEGER NOT NULL, sync_seen INTEGER NOT NULL DEFAULT 0,
            category TEXT NOT NULL, subcategory TEXT NOT NULL, mfr TEXT NOT NULL,
            package TEXT NOT NULL, joints INTEGER NOT NULL, manufacturer TEXT NOT NULL,
            library_type TEXT NOT NULL, preferred INTEGER NOT NULL,
            last_on_stock INTEGER NOT NULL, description TEXT NOT NULL,
            datasheet TEXT NOT NULL, stock INTEGER NOT NULL, price TEXT NOT NULL,
            attributes TEXT NOT NULL, rohs INTEGER, eccn TEXT NOT NULL,
            assembly INTEGER, assembly_process TEXT, assembly_mode TEXT,
            website_component_id TEXT, attrition TEXT NOT NULL
        );
        CREATE TABLE lcsc_components (
            lcsc INTEGER PRIMARY KEY NOT NULL, fetched_at INTEGER NOT NULL,
            manufacturer TEXT NOT NULL, attributes TEXT NOT NULL,
            image TEXT, url_slug TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(libraries, "JLCPARTS_DB_PATH", path)
    monkeypatch.setattr(dynamic, "JLCPARTS_DB_PATH", path)
    return path


@pytest.fixture
def remote_product():
    return {
        "productCode": "C131250",
        "productModel": "IR17-21C/TR8",
        "title": "EVERLIGHT IR17-21C/TR8",
        "productNameEn": "EMITTER IR 940nm SMD",
        "productDescEn": "Infrared emitter 940nm 0805",
        "parentCatalogName": "Optoelectronics",
        "catalogName": "LED Emitters - Infrared, UV, Visible",
        "brandNameEn": "EVERLIGHT",
        "encapStandard": "0805",
        "stockNumber": 11140,
        "isRohsCert": True,
        "pdfUrl": "https://example.test/part.pdf",
        "productImages": [
            "https://assets.lcsc.com/images/lcsc/900x900/c131250_front.jpg"
        ],
        "productPriceList": [
            {"ladder": 10, "usdPrice": 0.0589},
            {"ladder": 100, "usdPrice": 0.0461},
        ],
        "paramVOList": [
            {"paramNameEn": "Wavelength - Dominant", "paramValueEn": "940nm"},
            {"paramNameEn": "Forward Voltage (Vf)", "paramValueEn": "1.2V"},
        ],
    }


def test_exact_code_search_fetches_persists_and_reuses_remote_hit(
    jlc_library, remote_product, monkeypatch
):
    calls = []

    def fetch(code):
        calls.append(code)
        return remote_product

    monkeypatch.setattr(dynamic, "fetch_lcsc_product", fetch)

    first = libraries.search_jlcparts("C131250", page_size=10)
    second = libraries.search_jlcparts("C131250", page_size=10)

    assert first["total"] == second["total"] == 1
    assert first["items"][0]["lcsc"] == 131250
    assert first["items"][0]["mfr"] == "IR17-21C/TR8"
    assert first["items"][0]["manufacturer"] == "EVERLIGHT"
    assert first["items"][0]["package"] == "0805"
    assert first["items"][0]["stock"] == 11140
    assert first["items"][0]["attributes_dict"]["Wavelength - Dominant"] == "940nm"
    assert first["items"][0]["price_breaks"][0] == {"range": "10-99", "price": "0.0589"}
    assert first["items"][0]["source"] == "lcsc_dynamic"
    assert first["items"][0]["library_type"] == "lcsc_dynamic"
    assert calls == [131250]

    conn = sqlite3.connect(jlc_library)
    cached = conn.execute(
        "SELECT mfr, library_type, fetched_at, present FROM jlc_components WHERE lcsc = 131250"
    ).fetchone()
    cached_image = conn.execute(
        "SELECT image FROM lcsc_components WHERE lcsc = 131250"
    ).fetchone()
    conn.close()
    assert cached[0] == "IR17-21C/TR8"
    assert cached[1] == "lcsc_dynamic"
    assert cached[2] > 0
    assert cached[3] == 1
    assert cached_image == ("c131250_front.jpg",)


def test_detail_lookup_returns_same_dynamic_component(jlc_library, remote_product, monkeypatch):
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda code: remote_product)

    item = libraries.get_jlcparts_component(131250)

    assert item["lcsc"] == 131250
    assert item["source"] == "lcsc_dynamic"
    assert item["image_url_medium"].endswith("c131250_front.jpg")
    assert item["lcsc_url"] == "https://www.lcsc.com/search?q=C131250"


def test_search_and_detail_http_endpoints_return_dynamic_result(
    jlc_library, remote_product, monkeypatch
):
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda code: remote_product)
    client = TestClient(app)

    search = client.get("/api/libraries/jlcparts?q=C131250")
    detail = client.get("/api/libraries/jlcparts/131250")

    assert search.status_code == 200
    assert search.json()["items"][0]["source"] == "lcsc_dynamic"
    assert detail.status_code == 200
    assert detail.json()["source"] == "lcsc_dynamic"


def test_dynamic_lookup_only_runs_for_prefixed_exact_code(jlc_library, monkeypatch):
    calls = []
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda code: calls.append(code))

    libraries.search_jlcparts("131250")
    libraries.search_jlcparts("C131250xyz")
    libraries.search_jlcparts("IR17-21C/TR8")

    assert calls == []


def test_primary_catalog_hit_precedes_dynamic_lookup(jlc_library, remote_product, monkeypatch):
    path = jlc_library
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO jlc_components
        (lcsc, fetched_at, present, sync_seen, category, subcategory, mfr, package,
         joints, manufacturer, library_type, preferred, last_on_stock, description,
         datasheet, stock, price, attributes, rohs, eccn, assembly, assembly_process,
         assembly_mode, website_component_id, attrition)
        VALUES (131250, 1, 1, 0, 'Local category', '', 'LOCAL-PART', '0805',
                2, 'Local', 'base', 0, 0, 'local record', '', 5, '', '{}',
                1, '-', NULL, NULL, NULL, NULL, '{}')"""
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        dynamic,
        "fetch_lcsc_product",
        lambda code: pytest.fail("remote lookup must not replace a primary catalog hit"),
    )

    result = libraries.search_jlcparts("C131250")

    assert result["total"] == 1
    assert result["items"][0]["mfr"] == "LOCAL-PART"
    assert result["items"][0].get("source") != "lcsc_dynamic"


def test_exact_code_lookup_replaces_partial_model_hits_when_remote_has_the_code(
    jlc_library, remote_product, monkeypatch
):
    path = jlc_library
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO jlc_components
        (lcsc, fetched_at, present, sync_seen, category, subcategory, mfr, package,
         joints, manufacturer, library_type, preferred, last_on_stock, description,
         datasheet, stock, price, attributes, rohs, eccn, assembly, assembly_process,
         assembly_mode, website_component_id, attrition)
        VALUES (900001, 1, 1, 0, 'Other', '', 'C131250-ALT', '0603',
                2, 'Fixture', 'expand', 0, 1, 'Partial model hit', '', 50000,
                '', '{}', 1, '-', NULL, NULL, NULL, NULL, '{}')"""
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda code: remote_product)

    result = libraries.search_jlcparts("C131250", page_size=10)

    assert result["total"] == 1
    assert [item["lcsc"] for item in result["items"]] == [131250]
    assert result["items"][0]["source"] == "lcsc_dynamic"


def test_expired_dynamic_cache_refreshes_main_library_row(
    jlc_library, remote_product, monkeypatch
):
    calls = []

    def fetch(code):
        calls.append(code)
        return remote_product

    monkeypatch.setattr(dynamic, "fetch_lcsc_product", fetch)
    first = libraries.search_jlcparts("C131250")
    remote_product["stockNumber"] = 27
    monkeypatch.setattr(dynamic, "CACHE_TTL_SECONDS", 0)

    refreshed = libraries.search_jlcparts("C131250")

    assert first["items"][0]["stock"] == 11140
    assert refreshed["items"][0]["stock"] == 27
    assert calls == [131250, 131250]
    conn = sqlite3.connect(jlc_library)
    stock = conn.execute(
        "SELECT stock FROM jlc_components WHERE lcsc = 131250"
    ).fetchone()[0]
    conn.close()
    assert stock == 27


def test_dynamic_result_obeys_selected_category_filter(
    jlc_library, remote_product, monkeypatch
):
    calls = []

    def fetch(code):
        calls.append(code)
        return remote_product

    monkeypatch.setattr(dynamic, "fetch_lcsc_product", fetch)

    result = libraries.search_jlcparts("C131250", category="Capacitors")

    assert result["total"] == 0
    assert result["items"] == []
    assert calls == [131250]


def test_refreshed_dynamic_result_reapplies_filters_to_stale_row(
    jlc_library, remote_product, monkeypatch
):
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda code: remote_product)
    first = libraries.search_jlcparts("C131250", category="Optoelectronics")
    remote_product["parentCatalogName"] = "Capacitors"
    monkeypatch.setattr(dynamic, "CACHE_TTL_SECONDS", 0)

    refreshed = libraries.search_jlcparts("C131250", category="Optoelectronics")

    assert first["total"] == 1
    assert refreshed["total"] == 0
    assert refreshed["items"] == []


def test_public_lookup_validates_response_code_and_product_number(
    remote_product, monkeypatch
):
    requested = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"code": 200, "result": remote_product}).encode()

    def fake_urlopen(request, timeout):
        requested["url"] = request.full_url
        requested["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(dynamic, "urlopen", fake_urlopen)

    product = dynamic.fetch_lcsc_product(131250)

    assert product == remote_product
    assert parse_qs(urlparse(requested["url"]).query) == {
        "productCode": ["C131250"]
    }
    assert requested["timeout"] == dynamic.REQUEST_TIMEOUT_SECONDS

    remote_product["productCode"] = "C999999"
    assert dynamic.fetch_lcsc_product(131250) is None


def test_remote_miss_is_not_cached(jlc_library, monkeypatch):
    calls = []
    monkeypatch.setattr(dynamic, "fetch_lcsc_product", lambda code: calls.append(code))

    first = libraries.search_jlcparts("C999999")
    second = libraries.search_jlcparts("C999999")

    assert first["total"] == second["total"] == 0
    assert calls == [999999, 999999]
