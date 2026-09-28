import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services import external_library_service as lib_svc

client = TestClient(app)


def test_libraries_status():
    status = lib_svc.get_libraries_status()
    assert "altium" in status
    assert "kicad" in status
    assert "jlcparts" in status
    assert status["altium"]["available"] is True
    assert status["altium"]["count"] > 70000
    assert status["kicad"]["available"] is True
    assert status["kicad"]["count"] >= 22900
    assert status["jlcparts"]["available"] is True
    assert status["jlcparts"]["count"] >= 1000000


def test_altium_search():
    results = lib_svc.search_altium("0603", limit=5)
    assert results["total"] > 0
    assert len(results["items"]) > 0
    assert "lib_reference" in results["items"][0]
    assert "parameters" in results["items"][0]


def test_kicad_search():
    results = lib_svc.search_kicad("STM32", limit=5)
    assert results["total"] > 0
    assert len(results["items"]) > 0
    assert "name" in results["items"][0]
    assert "library" in results["items"][0]


def test_jlcparts_search():
    results = lib_svc.search_jlcparts("74HC", limit=5)
    assert results["total"] > 0
    assert len(results["items"]) > 0
    assert "mfr" in results["items"][0]


def test_api_libraries_status():
    response = client.get("/api/libraries/status")
    assert response.status_code == 200
    data = response.json()
    assert data["altium"]["available"] is True
    assert data["kicad"]["available"] is True
    assert data["jlcparts"]["available"] is True


def test_api_libraries_search():
    response = client.get("/api/libraries/search?q=10k&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "altium" in data
    assert "kicad" in data
    assert "jlcparts" in data


def test_api_category_endpoints():
    r_altium = client.get("/api/libraries/altium/categories")
    assert r_altium.status_code == 200
    assert isinstance(r_altium.json(), list)
    assert len(r_altium.json()) > 0

    r_kicad = client.get("/api/libraries/kicad/libraries")
    assert r_kicad.status_code == 200
    assert isinstance(r_kicad.json(), list)
    assert len(r_kicad.json()) > 0

    r_jlc = client.get("/api/libraries/jlcparts/categories")
    assert r_jlc.status_code == 200
    assert isinstance(r_jlc.json(), list)
    assert len(r_jlc.json()) > 0


def test_api_detail_endpoints():
    r_altium = client.get("/api/libraries/altium/1")
    assert r_altium.status_code == 200
    assert "lib_reference" in r_altium.json()

    r_kicad = client.get("/api/libraries/kicad/1")
    assert r_kicad.status_code == 200
    assert "raw_sexpr" in r_kicad.json()

    # Find valid LCSC part
    search_jlc = client.get("/api/libraries/jlcparts?page_size=1")
    first_lcsc = search_jlc.json()["items"][0]["lcsc"]
    r_jlc = client.get(f"/api/libraries/jlcparts/{first_lcsc}")
    assert r_jlc.status_code == 200
    assert "mfr" in r_jlc.json()


def test_web_library_pages():
    pages = [
        "/libraries/altium",
        "/libraries/altium/1",
        "/libraries/kicad",
        "/libraries/kicad/1",
        "/libraries/jlcparts",
    ]
    for url in pages:
        r = client.get(url)
        assert r.status_code == 200
        assert "<html" in r.text
