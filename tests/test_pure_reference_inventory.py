import pytest
from fastapi.testclient import TestClient
from app.main import app
from db.database import SessionLocal
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.project import Project
from app.models.project_part import ProjectPart

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_test_parts():
    """Ensure clean test environment by cleaning up test parts after test runs."""
    yield
    db = SessionLocal()
    try:
        test_parts = db.query(Part).filter(Part.note.like("TEST_%")).all()
        for p in test_parts:
            db.query(ProjectPart).filter(ProjectPart.part_id == p.id).delete()
            db.query(Inventory).filter(Inventory.part_id == p.id).delete()
            db.delete(p)
        db.commit()
    finally:
        db.close()


def test_add_and_hydrate_jlcparts():
    # 1. Add JLCParts C6374508 (IXDD609SITR)
    res = client.post("/api/inventory/add_part_to_inventory", json={
        "library_source": "jlcparts",
        "external_part_id": "6374508",
        "quantity": 25,
        "storage_location": "Box A-101",
        "note": "TEST_JLCPARTS_IXDD"
    })
    assert res.status_code == 200
    data = res.json()
    part_id = data["id"]
    assert data["library_source"] == "jlcparts"
    assert data["external_part_id"] == "6374508"
    assert data["storage_location"] == "Box A-101"
    assert data["note"] == "TEST_JLCPARTS_IXDD"
    assert data["quantity"] == 25
    assert "IXDD609" in data["name"]

    # 2. Get component details (full hydration)
    res = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
    assert res.status_code == 200
    details = res.json()
    assert details["id"] == part_id
    assert details["storage_location"] == "Box A-101"
    assert details["external_details"] is not None
    assert details["external_details"]["lcsc"] == 6374508
    assert "price_breaks" in details["external_details"]

    # 3. Clean up
    del_res = client.delete(f"/api/inventory/delete_part?part_id={part_id}")
    assert del_res.status_code == 200


def test_add_and_hydrate_altium():
    # 1. Add Altium component #1
    res = client.post("/api/inventory/add_part_to_inventory", json={
        "library_source": "altium",
        "external_part_id": "1",
        "quantity": 100,
        "storage_location": "SMD Reel Cabinet 1",
        "note": "TEST_ALTIUM_RESISTOR"
    })
    assert res.status_code == 200
    data = res.json()
    part_id = data["id"]
    assert data["library_source"] == "altium"
    assert data["external_part_id"] == "1"
    assert data["storage_location"] == "SMD Reel Cabinet 1"

    # 2. Verify details
    res = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
    assert res.status_code == 200
    details = res.json()
    assert details["external_details"] is not None
    assert "lib_reference" in details["external_details"]

    # 3. Clean up
    client.delete(f"/api/inventory/delete_part?part_id={part_id}")


def test_add_and_hydrate_kicad():
    # 1. Add KiCad symbol #1
    res = client.post("/api/inventory/add_part_to_inventory", json={
        "library_source": "kicad",
        "external_part_id": "1",
        "quantity": 10,
        "storage_location": "Drawer KiCad",
        "note": "TEST_KICAD_SYM"
    })
    assert res.status_code == 200
    data = res.json()
    part_id = data["id"]
    assert data["library_source"] == "kicad"

    # 2. Verify details has raw S-expression
    res = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
    assert res.status_code == 200
    details = res.json()
    assert details["external_details"] is not None
    assert "raw_sexpr" in details["external_details"]

    # 3. Clean up
    client.delete(f"/api/inventory/delete_part?part_id={part_id}")


def test_update_meta_location_and_note():
    # Create part
    res = client.post("/api/inventory/add_part_to_inventory", json={
        "library_source": "jlcparts",
        "external_part_id": "6374508",
        "quantity": 5,
        "storage_location": "Original Shelf",
        "note": "TEST_INITIAL_NOTE"
    })
    assert res.status_code == 200
    part_id = res.json()["id"]

    # Update metadata
    update_res = client.post("/api/inventory/update_meta", json={
        "part_id": part_id,
        "storage_location": "Updated Shelf B",
        "note": "TEST_UPDATED_NOTE"
    })
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["storage_location"] == "Updated Shelf B"
    assert updated["note"] == "TEST_UPDATED_NOTE"

    # Verify persistent in database
    get_res = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
    assert get_res.status_code == 200
    assert get_res.json()["storage_location"] == "Updated Shelf B"
    assert get_res.json()["note"] == "TEST_UPDATED_NOTE"

    # Clean up
    client.delete(f"/api/inventory/delete_part?part_id={part_id}")


def test_multiple_inventory_records_same_external_part():
    # User can have same physical component in two different boxes
    res1 = client.post("/api/inventory/add_part_to_inventory", json={
        "library_source": "jlcparts",
        "external_part_id": "6374508",
        "quantity": 50,
        "storage_location": "Lab Bench Drawer",
        "note": "TEST_DUPLICATE_1"
    })
    assert res1.status_code == 200
    id1 = res1.json()["id"]

    res2 = client.post("/api/inventory/add_part_to_inventory", json={
        "library_source": "jlcparts",
        "external_part_id": "6374508",
        "quantity": 200,
        "storage_location": "Warehouse Box 9",
        "note": "TEST_DUPLICATE_2"
    })
    assert res2.status_code == 200
    id2 = res2.json()["id"]

    assert id1 != id2

    # Clean up
    client.delete(f"/api/inventory/delete_part?part_id={id1}")
    client.delete(f"/api/inventory/delete_part?part_id={id2}")


def test_import_to_inventory_endpoint():
    # Test /api/libraries/import_to_inventory endpoint
    res = client.post("/api/libraries/import_to_inventory", params={
        "source": "jlcparts",
        "part_id": "6374508",
        "quantity": 30,
        "storage_location": "Test Location",
        "note": "TEST_LIB_IMPORT"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    part_id = data["part"]["id"]

    # Verify inventory
    get_res = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
    assert get_res.status_code == 200
    assert get_res.json()["quantity"] == 30

    # Clean up
    client.delete(f"/api/inventory/delete_part?part_id={part_id}")
