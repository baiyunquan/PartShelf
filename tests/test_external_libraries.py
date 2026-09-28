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
    assert len(results) > 0
    assert "lib_reference" in results[0]
    assert "parameters" in results[0]


def test_kicad_search():
    results = lib_svc.search_kicad("STM32", limit=5)
    assert len(results) > 0
    assert "name" in results[0]
    assert "library" in results[0]


def test_jlcparts_search():
    results = lib_svc.search_jlcparts("74HC", limit=5)
    assert len(results) > 0
    assert "mfr" in results[0]


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
