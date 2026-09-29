from fastapi.testclient import TestClient

from app.main import app
from db.database import SessionLocal
from app.models.inventory import Inventory
from app.models.part import Part
from app.models.project import Project
from app.models.project_part import ProjectPart


client = TestClient(app)


def test_bom_import_coalesces_identity_per_run_and_reimport_creates_new_batch():
    project_id = client.post(
        "/api/projects/api_add", json={"name": "TEST_BOM_BATCH"}
    ).json()["id"]
    item_a = {
        "row_index": 1, "quantity": 2, "selected": True,
        "library_source": "kicad", "external_part_id": "TEST_KICAD_BATCH_001",
        "confirmed_match": True,
    }
    item_b = {**item_a, "row_index": 2, "quantity": 3}
    created_part_ids = []
    try:
        first = client.post("/api/projects/bom/import", json={
            "target_type": "existing", "existing_project_id": project_id,
            "quantity_strategy": "overwrite", "items": [item_a, item_b],
        })
        assert first.status_code == 200, first.text
        first_details = client.get(f"/api/projects/{project_id}").json()
        assert first_details["parts_count"] == 1
        first_part_id = first_details["parts"][0]["part_id"]
        created_part_ids.append(first_part_id)
        assert first_details["parts"][0]["quantity_needed"] == 5
        assert first_details["parts"][0]["quantity_available"] == 0

        second = client.post("/api/projects/bom/import", json={
            "target_type": "existing", "existing_project_id": project_id,
            "quantity_strategy": "overwrite", "items": [{**item_a, "quantity": 7}],
        })
        assert second.status_code == 200, second.text
        second_details = client.get(f"/api/projects/{project_id}").json()
        assert second_details["parts_count"] == 2
        assert sorted(part["quantity_needed"] for part in second_details["parts"]) == [5, 7]
        created_part_ids = [part["part_id"] for part in second_details["parts"]]
        assert len(set(created_part_ids)) == 2

        db = SessionLocal()
        try:
            records = db.query(Part).filter(
                Part.library_source == "kicad",
                Part.external_part_id == "TEST_KICAD_BATCH_001",
            ).all()
            assert {part.id for part in records} == set(created_part_ids)
            assert all(part.inventory.quantity_available == 0 for part in records)
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            db.query(ProjectPart).filter(ProjectPart.project_id == project_id).delete()
            for part_id in created_part_ids:
                db.query(Inventory).filter(Inventory.part_id == part_id).delete()
                db.query(Part).filter(Part.id == part_id).delete()
            db.query(Project).filter(Project.id == project_id).delete()
            db.commit()
        finally:
            db.close()


def test_bom_import_rejects_loose_parts_system_project():
    loose = next(
        project for project in client.get("/api/projects/").json()
        if project.get("system_key") == "loose_parts"
    )
    response = client.post("/api/projects/bom/import", json={
        "target_type": "existing", "existing_project_id": loose["id"],
        "items": [{
            "row_index": 1, "quantity": 1, "selected": True,
            "is_custom": True, "custom_name": "TEST_LOOSE_IMPORT",
        }],
    })
    assert response.status_code == 400
    assert "system" in response.json()["detail"].lower()


def test_bom_import_does_not_reuse_or_change_an_existing_inventory_batch():
    project_id = client.post(
        "/api/projects/api_add", json={"name": "TEST_BOM_EXISTING_STOCK"}
    ).json()["id"]
    old_part = Part(
        library_source="kicad",
        external_part_id="TEST_KICAD_ALREADY_STOCKED",
        note="TEST_BOM_EXISTING_STOCK_OLD",
    )
    db = SessionLocal()
    db.add(old_part)
    db.flush()
    db.add(Inventory(part_id=old_part.id, quantity_available=42))
    db.commit()
    old_part_id = old_part.id
    db.close()
    new_part_id = None
    try:
        response = client.post("/api/projects/bom/import", json={
            "target_type": "existing",
            "existing_project_id": project_id,
            "items": [{
                "row_index": 1,
                "quantity": 6,
                "selected": True,
                "library_source": "kicad",
                "external_part_id": "TEST_KICAD_ALREADY_STOCKED",
                "inventory_part_id": old_part_id,
                "status": "in_inventory",
                "confirmed_match": True,
            }],
        })
        assert response.status_code == 200, response.text
        details = client.get(f"/api/projects/{project_id}").json()
        assert details["parts_count"] == 1
        new_part_id = details["parts"][0]["part_id"]
        assert new_part_id != old_part_id
        assert details["parts"][0]["quantity_needed"] == 6
        assert details["parts"][0]["quantity_available"] == 0

        db = SessionLocal()
        try:
            assert db.query(Inventory).filter_by(part_id=old_part_id).one().quantity_available == 42
            assert db.query(Inventory).filter_by(part_id=new_part_id).one().quantity_available == 0
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            db.query(ProjectPart).filter(ProjectPart.project_id == project_id).delete()
            if new_part_id:
                db.query(Inventory).filter(Inventory.part_id == new_part_id).delete()
                db.query(Part).filter(Part.id == new_part_id).delete()
            db.query(Inventory).filter(Inventory.part_id == old_part_id).delete()
            db.query(Part).filter(Part.id == old_part_id).delete()
            db.query(Project).filter(Project.id == project_id).delete()
            db.commit()
        finally:
            db.close()
