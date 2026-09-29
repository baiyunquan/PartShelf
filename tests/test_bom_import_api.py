import os
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
SAMPLE_FILE = r"E:\workspace\RadioLabRepoBackend\BOM\BOM_Board_RP2350A_PCB1_1_2026-09-29.xlsx"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield
    db = SessionLocal()
    try:
        # Clean up test projects
        test_projs = db.query(Project).filter(Project.name.like("TEST_%")).all()
        for p in test_projs:
            db.query(ProjectPart).filter(ProjectPart.project_id == p.id).delete()
            db.delete(p)

        # Clean up test parts
        test_parts = db.query(Part).filter(Part.note.like("%TEST_%")).all()
        for pt in test_parts:
            db.query(ProjectPart).filter(ProjectPart.part_id == pt.id).delete()
            db.query(Inventory).filter(Inventory.part_id == pt.id).delete()
            db.delete(pt)

        # Clean up test custom components
        test_custom = db.query(CustomComponent).filter(CustomComponent.name.like("TEST_%")).all()
        for c in test_custom:
            db.delete(c)

        db.commit()
    finally:
        db.close()


def test_bom_preview_api():
    assert os.path.exists(SAMPLE_FILE)
    with open(SAMPLE_FILE, "rb") as f:
        res = client.post(
            "/api/projects/bom/preview",
            files={"file": ("BOM_Board_RP2350A_PCB1_1_2026-09-29.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
    assert res.status_code == 200
    data = res.json()
    assert data["filename"] == "BOM_Board_RP2350A_PCB1_1_2026-09-29.xlsx"
    assert "RP2350" in data["suggested_project_name"]
    assert data["total_rows"] == 42
    assert len(data["items"]) == 42
    assert "in_inventory_count" in data
    assert "matched_library_count" in data
    assert "unmatched_count" in data


def test_bom_custom_part_api():
    res = client.post("/api/projects/bom/custom_part", json={
        "name": "TEST_M2_SCREW",
        "manufacturer": "Hardware Mfr",
        "package": "M2x6",
        "part_type": "Mechanical",
        "description": "TEST mechanical mounting screw"
    })
    assert res.status_code == 200
    data = res.json()
    custom_id = data["id"]
    assert data["name"] == "TEST_M2_SCREW"

    # Test hydration via resolve_part_summary
    summary = resolve_part_summary("custom", str(custom_id))
    assert summary["name"] == "TEST_M2_SCREW"
    assert summary["package"] == "M2x6"
    assert summary["manufacturer"] == "Hardware Mfr"


def test_bom_import_new_project():
    # 1. Preview BOM
    with open(SAMPLE_FILE, "rb") as f:
        preview_res = client.post(
            "/api/projects/bom/preview",
            files={"file": ("BOM_Board_RP2350A_PCB1_1_2026-09-29.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()

    # Pick top 5 items for import test (including matched library and custom item)
    items_to_import = preview_data["items"][:5]
    # Mark one item as custom
    items_to_import[0]["is_custom"] = True
    items_to_import[0]["custom_name"] = "TEST_CUSTOM_LED"
    items_to_import[0]["custom_manufacturer"] = "TEST_OPTO"
    items_to_import[0]["custom_package"] = "0603"

    # 2. Execute Import as new project
    import_payload = {
        "target_type": "new",
        "project_name": "TEST_RP2350_IMPORT_PROJECT",
        "project_description": "Automated import test",
        "quantity_strategy": "overwrite",
        "items": items_to_import
    }
    import_res = client.post("/api/projects/bom/import", json=import_payload)
    assert import_res.status_code == 200
    import_result = import_res.json()
    assert import_result["success"] is True
    project_id = import_result["project_id"]
    assert import_result["project_name"] == "TEST_RP2350_IMPORT_PROJECT"
    assert import_result["imported_parts_count"] > 0

    # 3. Verify Project Details
    details_res = client.get(f"/api/projects/{project_id}")
    assert details_res.status_code == 200
    details = details_res.json()
    assert details["name"] == "TEST_RP2350_IMPORT_PROJECT"
    assert details["parts_count"] == import_result["imported_parts_count"]


def test_bom_import_existing_project_strategies():
    # 1. Create base project
    proj_res = client.post("/api/projects/api_add", json={
        "name": "TEST_EXISTING_PROJECT",
        "description": "Base project"
    })
    assert proj_res.status_code == 200
    project_id = proj_res.json()["id"]

    # 2. Import one custom part with quantity 5
    item = {
        "row_index": 1,
        "quantity": 5,
        "selected": True,
        "is_custom": True,
        "custom_name": "TEST_DIODE",
        "custom_manufacturer": "Diodes Inc",
        "custom_package": "SOD-123"
    }
    res1 = client.post("/api/projects/bom/import", json={
        "target_type": "existing",
        "existing_project_id": project_id,
        "quantity_strategy": "overwrite",
        "items": [item]
    })
    assert res1.status_code == 200

    # Verify needed quantity is 5
    details1 = client.get(f"/api/projects/{project_id}").json()
    assert details1["parts_count"] == 1
    part_id = details1["parts"][0]["part_id"]
    assert details1["parts"][0]["quantity_needed"] == 5

    # 3. Import same part with quantity 10 and strategy 'add'
    item_reimport_add = {
        "row_index": 1,
        "quantity": 10,
        "selected": True,
        "inventory_part_id": part_id,
        "status": "in_inventory"
    }
    res2 = client.post("/api/projects/bom/import", json={
        "target_type": "existing",
        "existing_project_id": project_id,
        "quantity_strategy": "add",
        "items": [item_reimport_add]
    })
    assert res2.status_code == 200
    details2 = client.get(f"/api/projects/{project_id}").json()
    assert details2["parts"][0]["quantity_needed"] == 15  # 5 + 10

    # 4. Import same part with quantity 8 and strategy 'overwrite'
    item_reimport_overwrite = {
        "row_index": 1,
        "quantity": 8,
        "selected": True,
        "inventory_part_id": part_id,
        "status": "in_inventory"
    }
    res3 = client.post("/api/projects/bom/import", json={
        "target_type": "existing",
        "existing_project_id": project_id,
        "quantity_strategy": "overwrite",
        "items": [item_reimport_overwrite]
    })
    assert res3.status_code == 200
    details3 = client.get(f"/api/projects/{project_id}").json()
    assert details3["parts"][0]["quantity_needed"] == 8  # overwritten to 8
