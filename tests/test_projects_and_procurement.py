from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.main import app
from db.database import SessionLocal
from app.models.part import Part
from app.models.project import Project
from app.models.project_part import ProjectPart
from app.models.inventory import Inventory
from app.models.custom_component import CustomComponent

client = TestClient(app)
_TEST_PREFIX = f"TEST_PROJECTS_{uuid4().hex}"
_PROJECT_NAME = f"{_TEST_PREFIX}_RF_TRANSCEIVER_BOARD"
_PART_NOTE = f"{_TEST_PREFIX}_PROJECT_CRUD_PART"
_CUSTOM_PART_NAME = f"{_TEST_PREFIX}_PROJECT_PART"

@pytest.fixture(autouse=True)
def clean_db():
    yield
    db = SessionLocal()
    try:
        parts = db.query(Part).filter(Part.note == _PART_NOTE).all()
        custom_ids = [int(part.external_part_id) for part in parts if part.library_source == "custom"]
        part_ids = [part.id for part in parts]
        if part_ids:
            db.query(ProjectPart).filter(ProjectPart.part_id.in_(part_ids)).delete(synchronize_session=False)
            db.query(Inventory).filter(Inventory.part_id.in_(part_ids)).delete(synchronize_session=False)
            db.query(Part).filter(Part.id.in_(part_ids)).delete(synchronize_session=False)
        if custom_ids:
            db.query(CustomComponent).filter(CustomComponent.id.in_(custom_ids)).delete(synchronize_session=False)
        projects = db.query(Project).filter(Project.name == _PROJECT_NAME).all()
        project_ids = [project.id for project in projects]
        if project_ids:
            db.query(ProjectPart).filter(ProjectPart.project_id.in_(project_ids)).delete(synchronize_session=False)
            db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

def test_project_crud_and_procurement():
    db = SessionLocal()
    component = CustomComponent(
        name=_CUSTOM_PART_NAME, manufacturer="Test", package="0603", part_type="Capacitor"
    )
    db.add(component)
    db.flush()
    test_part = Part(
        library_source="custom", external_part_id=str(component.id), note=_PART_NOTE
    )
    db.add(test_part)
    db.flush()
    db.add(Inventory(part_id=test_part.id, quantity_available=100))
    db.commit()
    part_id = test_part.id
    db.close()

    # 1. Create a project
    res = client.post("/api/projects/api_add", json={
        "name": _PROJECT_NAME,
        "description": "2.4GHz transceivers"
    })
    assert res.status_code == 200
    proj_data = res.json()
    project_id = proj_data["id"]
    assert proj_data["name"] == _PROJECT_NAME

    # 2. Get all projects
    res = client.get("/api/projects/")
    assert res.status_code == 200
    projects = res.json()
    assert any(p["id"] == project_id for p in projects)

    # 3. Use the test-owned part and stock row seeded above.
    res = client.get("/api/inventory/get_part_by_id", params={"part_id": part_id})
    test_part_data = res.json()
    current_stock = test_part_data["quantity"]

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
