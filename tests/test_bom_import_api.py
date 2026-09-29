from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.main import app
from db.database import SessionLocal
from app.models.project import Project
from app.models.project_part import ProjectPart
from app.models.part import Part
from app.models.inventory import Inventory
from app.models.custom_component import CustomComponent
from app.services.external_library_service import resolve_part_summary

client = TestClient(app)
_TEST_PREFIX = f"TEST_BOM_API_{uuid4().hex}"
_REJECT_PROJECT_NAME = f"{_TEST_PREFIX}_REJECT_UNCONFIRMED"
_NEW_PROJECT_NAME = f"{_TEST_PREFIX}_NEW_PROJECT"
_CUSTOM_COMPONENT_NAMES = {
    f"{_TEST_PREFIX}_M2_SCREW",
    f"{_TEST_PREFIX}_CUSTOM_DIODE",
}


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield
    db = SessionLocal()
    try:
        project_names = {_REJECT_PROJECT_NAME, _NEW_PROJECT_NAME}
        test_projs = db.query(Project).filter(Project.name.in_(project_names)).all()
        for p in test_projs:
            db.query(ProjectPart).filter(ProjectPart.project_id == p.id).delete()
            db.delete(p)

        test_parts = db.query(Part).filter(
            Part.note == f"Imported from BOM for {_NEW_PROJECT_NAME}"
        ).all()
        for pt in test_parts:
            db.query(ProjectPart).filter(ProjectPart.part_id == pt.id).delete()
            db.query(Inventory).filter(Inventory.part_id == pt.id).delete()
            db.delete(pt)

        test_custom = db.query(CustomComponent).filter(
            CustomComponent.name.in_(_CUSTOM_COMPONENT_NAMES)
        ).all()
        for c in test_custom:
            db.delete(c)

        db.commit()
    finally:
        db.close()


def test_bom_preview_api():
    csv_content = (
        "Quantity,Designator,Comment,Value,Footprint,Primary Category,Pin Count\n"
        "2,U1,Example IC,Example IC,Package-Unknown,Integrated Circuits,8\n"
    )
    res = client.post(
        "/api/projects/bom/preview",
        files={"file": ("BOM_fixture.csv", csv_content, "text/csv")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["filename"] == "BOM_fixture.csv"
    assert data["suggested_project_name"] == "fixture"
    assert data["total_rows"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["designator"] == "U1"
    assert data["items"][0]["value"] == "Example IC"
    assert "in_inventory_count" in data
    assert "matched_library_count" in data
    assert "unmatched_count" in data


def test_import_endpoint_requires_manual_confirmation_for_substitute():
    response = client.post("/api/projects/bom/import", json={
        "target_type": "new", "project_name": _REJECT_PROJECT_NAME,
        "items": [{
            "row_index": 1, "selected": True, "raw_supplier_part": "C999999999",
            "library_source": "jlcparts", "external_part_id": "100002",
            "status": "matched_library", "confirmed_match": False,
        }],
    })
    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"]


def test_bom_custom_part_api():
    res = client.post("/api/projects/bom/custom_part", json={
        "name": f"{_TEST_PREFIX}_M2_SCREW",
        "manufacturer": "Hardware Mfr",
        "package": "M2x6",
        "part_type": "Mechanical",
        "description": "TEST mechanical mounting screw"
    })
    assert res.status_code == 200
    data = res.json()
    custom_id = data["id"]
    assert data["name"] == f"{_TEST_PREFIX}_M2_SCREW"

    # Test hydration via resolve_part_summary
    summary = resolve_part_summary("custom", str(custom_id))
    assert summary["name"] == f"{_TEST_PREFIX}_M2_SCREW"
    assert summary["package"] == "M2x6"
    assert summary["manufacturer"] == "Hardware Mfr"


def test_bom_import_new_project():
    item = {
        "row_index": 1,
        "quantity": 3,
        "designator": "D_TEST",
        "selected": True,
        "is_custom": True,
        "custom_name": f"{_TEST_PREFIX}_CUSTOM_DIODE",
        "custom_manufacturer": "TEST_MANUFACTURER",
        "custom_package": "SOD-123",
    }
    import_payload = {
        "target_type": "new",
        "project_name": _NEW_PROJECT_NAME,
        "project_description": "Synthetic BOM API test",
        "items": [item],
    }
    import_res = client.post("/api/projects/bom/import", json=import_payload)
    assert import_res.status_code == 200
    import_result = import_res.json()
    assert import_result["success"] is True
    project_id = import_result["project_id"]
    assert import_result["project_name"] == _NEW_PROJECT_NAME
    assert import_result["imported_parts_count"] == 1

    details_res = client.get(f"/api/projects/{project_id}")
    assert details_res.status_code == 200
    details = details_res.json()
    assert details["name"] == _NEW_PROJECT_NAME
    assert details["parts_count"] == 1
    part = details["parts"][0]
    assert part["quantity_needed"] == 3
    assert part["quantity_available"] == 0
