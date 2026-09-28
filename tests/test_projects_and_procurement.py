import pytest
from fastapi.testclient import TestClient
from app.main import app
from db.database import SessionLocal
from app.models.part import Part
from app.models.project import Project
from app.models.project_part import ProjectPart
from app.models.inventory import Inventory
from app.models.manufacturer import Manufacturer
from app.models.package import Package
from app.models.type import Type

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db():
    db = SessionLocal()
    try:
        db.query(ProjectPart).delete()
        db.query(Project).delete()
        db.commit()
    finally:
        db.close()

def test_project_crud_and_procurement():
    # 1. Create a project
    res = client.post("/api/projects/api_add", json={
        "name": "RF Transceiver Board",
        "description": "2.4GHz transceivers"
    })
    assert res.status_code == 200
    proj_data = res.json()
    project_id = proj_data["id"]
    assert proj_data["name"] == "RF Transceiver Board"

    # 2. Get all projects
    res = client.get("/api/projects/")
    assert res.status_code == 200
    projects = res.json()
    assert any(p["id"] == project_id for p in projects)

    # 3. Add a part to inventory (or get existing parts)
    res = client.get("/api/inventory/get_parts_inventory")
    parts = res.json()
    assert len(parts) > 0
    test_part = parts[0]
    part_id = test_part["id"]
    current_stock = test_part["quantity"]

    # 4. Associate part with the project, requesting 500 units
    needed_qty = current_stock + 200
    res = client.post(f"/api/projects/{project_id}/add_part", json={
        "part_id": part_id,
        "quantity_needed": needed_qty
    })
    assert res.status_code == 200

    # 5. Check project details and shortage
    res = client.get(f"/api/projects/{project_id}")
    assert res.status_code == 200
    details = res.json()
    assert details["parts_count"] == 1
    part_item = details["parts"][0]
    assert part_item["part_id"] == part_id
    assert part_item["quantity_needed"] == needed_qty
    assert part_item["shortage"] == 200  # needed - current_stock

    # 6. Check that part in inventory now reflects the project
    res = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
    assert res.status_code == 200
    part_details = res.json()
    assert "projects" in part_details
    assert any(p["id"] == project_id for p in part_details["projects"])

    # 7. Check global procurement list
    res = client.get("/api/projects/procurement/list")
    assert res.status_code == 200
    procurement = res.json()
    target = next((item for item in procurement if item["part_id"] == part_id), None)
    assert target is not None
    assert target["shortage"] == 200
    assert target["total_needed"] == needed_qty
    assert any(p["id"] == project_id for p in target["projects"])

    # 8. Update quantity needed to be less than stock
    less_qty = max(0, current_stock - 10)
    res = client.post(f"/api/projects/{project_id}/update_part_quantity?part_id={part_id}&quantity_needed={less_qty}")
    assert res.status_code == 200

    # Shortage should now be 0
    res = client.get(f"/api/projects/{project_id}")
    details = res.json()
    assert details["parts"][0]["shortage"] == 0

    # 9. Remove part from project
    res = client.delete(f"/api/projects/{project_id}/remove_part/{part_id}")
    assert res.status_code == 200

    res = client.get(f"/api/projects/{project_id}")
    assert res.json()["parts_count"] == 0

    # 10. Delete project
    res = client.delete(f"/api/projects/{project_id}")
    assert res.status_code == 200
