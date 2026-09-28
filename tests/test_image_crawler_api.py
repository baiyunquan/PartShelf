import pytest
import base64
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.services import external_library_service as lib_svc

client = TestClient(app)

# 1x1 transparent GIF/JPEG sample in base64
SAMPLE_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def test_crawler_tasks_endpoint():
    """Verify that tasks endpoint returns batch of LCSC IDs needing images."""
    response = client.get("/api/libraries/jlcparts/crawler/tasks?limit=10&cursor=0")
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data
    assert "cursor" in data
    assert "limit" in data
    assert "count" in data
    assert len(data["tasks"]) <= 10
    if data["tasks"]:
        first = data["tasks"][0]
        assert isinstance(first, dict)
        assert "lcsc" in first
        assert "website_component_id" in first
        assert data["cursor"] >= first["lcsc"]


def test_crawler_stats_endpoint():
    """Verify that stats endpoint returns accurate database counts."""
    response = client.get("/api/libraries/jlcparts/crawler/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_components" in data
    assert "with_image" in data
    assert "no_image" in data
    assert "remaining" in data
    assert "local_image_files" in data
    assert data["total_components"] > 0
    assert data["remaining"] >= 0


def test_crawler_upload_and_local_image_resolution():
    """Verify uploading an image persists locally and is reflected in jlcparts queries."""
    test_lcsc = 999999999  # Safe high ID for testing
    test_file = lib_svc.PARTS_IMAGES_DIR / f"{test_lcsc}.jpg"

    try:
        # 1. Upload simulated image
        payload = {
            "lcsc": f"C{test_lcsc}",  # Test string parsing with 'C' prefix
            "image_base64": f"data:image/png;base64,{SAMPLE_TINY_PNG_B64}",
            "image_url": "https://alimg.szlcsc.com/test.jpg",
            "product_model": "TEST-CHIP-MODEL",
            "has_image": True
        }
        res = client.post("/api/libraries/jlcparts/crawler/upload", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["lcsc"] == test_lcsc
        assert data["has_image"] is True
        assert data["image_path"] == f"/static/images/parts/{test_lcsc}.jpg"

        # Verify file exists on disk
        assert test_file.exists()
        assert test_file.stat().st_size > 0

        # Verify _build_part_image_urls resolves to local path
        urls = lib_svc._build_part_image_urls(test_lcsc, f"{test_lcsc}.jpg")
        assert urls["image_url_small"] == f"/static/images/parts/{test_lcsc}.jpg"
        assert urls["image_url_medium"] == f"/static/images/parts/{test_lcsc}.jpg"

    finally:
        # Cleanup test image file and DB record
        if test_file.exists():
            test_file.unlink()
        conn = lib_svc.get_rw_connection(lib_svc.JLCPARTS_DB_PATH)
        if conn:
            conn.execute("DELETE FROM lcsc_components WHERE lcsc = ?", (test_lcsc,))
            conn.commit()
            conn.close()


def test_crawler_upload_no_image():
    """Verify marking a part as having no image on LCSC."""
    test_lcsc = 999999998

    try:
        payload = {
            "lcsc": test_lcsc,
            "image_base64": None,
            "has_image": False
        }
        res = client.post("/api/libraries/jlcparts/crawler/upload", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["has_image"] is False

        # Verify in DB it's marked as NONE
        conn = lib_svc.get_connection(lib_svc.JLCPARTS_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT image FROM lcsc_components WHERE lcsc = ?", (test_lcsc,))
        row = cur.fetchone()
        assert row is not None
        assert row["image"] == "NONE"
        conn.close()

        # Verify _build_part_image_urls returns None
        urls = lib_svc._build_part_image_urls(test_lcsc, "NONE")
        assert urls["image_url_small"] is None

    finally:
        conn = lib_svc.get_rw_connection(lib_svc.JLCPARTS_DB_PATH)
        if conn:
            conn.execute("DELETE FROM lcsc_components WHERE lcsc = ?", (test_lcsc,))
            conn.commit()
            conn.close()


def test_claim_and_release_task():
    """Verify atomic claiming of tasks for concurrent workers."""
    # Claim task 1
    res1 = client.get("/api/libraries/jlcparts/crawler/claim-task")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "success"
    task1 = data1["task"]
    assert task1 is not None
    assert "lcsc" in task1
    assert "website_component_id" in task1

    # Claim task 2 (must be different from task 1!)
    res2 = client.get("/api/libraries/jlcparts/crawler/claim-task")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "success"
    task2 = data2["task"]
    assert task2 is not None
    assert task2["lcsc"] != task1["lcsc"], "Concurrent tasks must be distinct!"

    # Release both tasks
    rel1 = client.post(f"/api/libraries/jlcparts/crawler/release-task?lcsc={task1['lcsc']}")
    assert rel1.status_code == 200
    assert rel1.json()["released"] is True

    rel2 = client.post(f"/api/libraries/jlcparts/crawler/release-task?lcsc={task2['lcsc']}")
    assert rel2.status_code == 200
    assert rel2.json()["released"] is True
