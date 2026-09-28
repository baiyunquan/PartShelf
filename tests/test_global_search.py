import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_quick_search_api():
    """Verify live autocomplete API returns structured results across all 4 libraries."""
    resp = client.get("/api/search/quick?q=stm32")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "stm32"
    assert "total_matches" in data
    assert "inventory" in data
    assert "jlcparts" in data
    assert "altium" in data
    assert "kicad" in data

    # Verify jlcparts, altium, and kicad matches
    assert data["jlcparts"]["total"] > 0
    assert len(data["jlcparts"]["items"]) > 0
    assert "url" in data["jlcparts"]["items"][0]

    assert data["altium"]["total"] > 0
    assert len(data["altium"]["items"]) > 0
    assert "url" in data["altium"]["items"][0]

    assert data["kicad"]["total"] > 0
    assert len(data["kicad"]["items"]) > 0
    assert "url" in data["kicad"]["items"][0]


def test_quick_search_empty():
    """Verify quick search with empty or single char query."""
    resp = client.get("/api/search/quick?q=a")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "a"


def test_aggregate_search_all():
    """Verify aggregate search overview tab (tab=all)."""
    resp = client.get("/api/search/aggregate?q=0603&tab=all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tab"] == "all"
    assert "counts" in data
    assert data["counts"]["jlcparts"] > 0
    assert data["counts"]["altium"] > 0
    assert len(data["jlcparts"]["items"]) <= 5
    assert len(data["altium"]["items"]) <= 5


def test_aggregate_search_jlcparts_tab():
    """Verify JLCPCB tab paginated search."""
    resp = client.get("/api/search/aggregate?q=ESP32&tab=jlcparts&page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tab"] == "jlcparts"
    assert data["total"] > 0
    assert len(data["items"]) > 0
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert "total_pages" in data


def test_aggregate_search_altium_tab():
    """Verify Altium tab paginated search."""
    resp = client.get("/api/search/aggregate?q=resistor&tab=altium&page=1&page_size=15")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tab"] == "altium"
    assert data["total"] > 0
    assert len(data["items"]) > 0
    assert data["page_size"] == 15


def test_aggregate_search_kicad_tab():
    """Verify KiCad tab paginated search."""
    resp = client.get("/api/search/aggregate?q=amplifier&tab=kicad&page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tab"] == "kicad"
    assert data["total"] > 0
    assert len(data["items"]) > 0


def test_aggregate_search_inventory_tab():
    """Verify Inventory tab search."""
    resp = client.get("/api/search/aggregate?q=&tab=inventory&page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tab"] == "inventory"
    assert "items" in data
    assert "total" in data


def test_search_web_page_render():
    """Verify /search HTML template renders successfully."""
    resp = client.get("/search?q=STM32")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "centerSearchInput" in resp.text
    assert "tab-all-btn" in resp.text
    assert "topNavbarSearchInput" in resp.text
