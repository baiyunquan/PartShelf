from fastapi.testclient import TestClient

from app.main import app
from db.database import SessionLocal
from app.models.custom_component import CustomComponent
from app.models.inventory import Inventory
from app.models.part import Part
from app.models.project import Project
from app.models.project_part import ProjectPart
from app.models.warehouse_placement import WarehousePlacement


client = TestClient(app)


def _create_custom_part(name: str, quantity: int = 0) -> int:
    db = SessionLocal()
    try:
        component = CustomComponent(
            name=name, manufacturer="Test", package="0603", part_type="Capacitor"
        )
        db.add(component)
        db.flush()
        part = Part(library_source="custom", external_part_id=str(component.id))
        db.add(part)
        db.flush()
        db.add(Inventory(part_id=part.id, quantity_available=quantity))
        db.commit()
        return part.id
    finally:
        db.close()


def _delete_part(part_id: int) -> None:
    db = SessionLocal()
    try:
        part = db.query(Part).filter(Part.id == part_id).first()
        custom_id = part.external_part_id if part and part.library_source == "custom" else None
        db.query(WarehousePlacement).filter(WarehousePlacement.part_id == part_id).delete()
        db.query(ProjectPart).filter(ProjectPart.part_id == part_id).delete()
        db.query(Inventory).filter(Inventory.part_id == part_id).delete()
        db.query(Part).filter(Part.id == part_id).delete()
        if custom_id and str(custom_id).isdigit():
            db.query(CustomComponent).filter(CustomComponent.id == int(custom_id)).delete()
        db.commit()
    finally:
        db.close()


def test_warehouse_contents_returns_config_and_unplaced_inventory_parts():
    part_id = _create_custom_part("TEST_WAREHOUSE_UNPLACED", 17)
    try:
        response = client.get("/api/warehouse/contents")
        assert response.status_code == 200
        cabinets = response.json()["cabinets"]
        assert [cabinet["id"] for cabinet in cabinets] == ["BOX-000", "BOX-001", "BOX-002"]
        drawers = [drawer for cabinet in cabinets for group in cabinet["drawerGroups"] for drawer in group["drawers"]]
        assert len(drawers) == 117
        assert all(drawer["parts"] == [] for drawer in drawers)

        inventory = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}")
        assert inventory.status_code == 200
        assert inventory.json()["warehouse_status"] == "not_in_warehouse"
        assert inventory.json()["warehouse_box_id"] is None
        assert inventory.json()["warehouse_drawer_code"] is None
        assert inventory.json()["quantity"] == 17
    finally:
        _delete_part(part_id)


def test_inventory_warehouse_filter_keeps_all_parts_by_default():
    part_id = _create_custom_part("TEST_WAREHOUSE_FILTER", 3)
    try:
        all_parts = client.get("/api/inventory/get_parts_inventory").json()
        unplaced = client.get(
            "/api/inventory/get_parts_inventory?warehouse_status=not_in_warehouse"
        ).json()
        placed = client.get(
            "/api/inventory/get_parts_inventory?warehouse_status=in_warehouse"
        ).json()
        assert any(part["id"] == part_id for part in all_parts)
        assert any(part["id"] == part_id for part in unplaced)
        assert placed == []
    finally:
        _delete_part(part_id)


def test_placement_marks_part_in_warehouse_and_serves_required_photo_blob():
    part_id = _create_custom_part("TEST_WAREHOUSE_PLACED", 4)
    photo = b"warehouse-photo-data"
    db = SessionLocal()
    try:
        db.add(WarehousePlacement(
            part_id=part_id,
            cabinet_id="BOX-001",
            drawer_code="S-04",
            photo_data=photo,
            photo_mime_type="image/jpeg",
        ))
        db.commit()
    finally:
        db.close()

    try:
        inventory = client.get(f"/api/inventory/get_part_by_id?part_id={part_id}").json()
        assert inventory["warehouse_status"] == "in_warehouse"
        assert inventory["warehouse_box_id"] == "BOX-001"
        assert inventory["warehouse_drawer_code"] == "S-04"
        assert inventory["warehouse_photo_url"] == f"/api/warehouse/parts/{part_id}/photo"
        placed_parts = client.get(
            "/api/inventory/get_parts_inventory?warehouse_status=in_warehouse"
        ).json()
        assert any(part["id"] == part_id for part in placed_parts)

        contents = client.get("/api/warehouse/contents").json()
        drawer = next(
            drawer for cabinet in contents["cabinets"] if cabinet["id"] == "BOX-001"
            for group in cabinet["drawerGroups"] for drawer in group["drawers"]
            if drawer["code"] == "S-04"
        )
        assert drawer["part_count"] == 1
        assert drawer["available_quantity"] == 4
        assert drawer["parts"][0]["id"] == part_id

        image = client.get(inventory["warehouse_photo_url"])
        assert image.status_code == 200
        assert image.content == photo
        assert image.headers["content-type"] == "image/jpeg"
    finally:
        _delete_part(part_id)


def test_loose_parts_project_is_system_read_only_and_summarizes_unassigned_stock():
    part_id = _create_custom_part("TEST_LOOSE_PART", 23)
    try:
        db = SessionLocal()
        try:
            db.add(WarehousePlacement(
                part_id=part_id,
                cabinet_id="BOX-000",
                drawer_code="L-01",
                photo_data=b"loose-part-photo",
                photo_mime_type="image/jpeg",
            ))
            db.commit()
        finally:
            db.close()

        projects = client.get("/api/projects/?lang=en").json()
        loose = next(project for project in projects if project["system_key"] == "loose_parts")
        assert loose["name"] == "Loose Parts"
        assert loose["is_system"] is True

        details = client.get(f"/api/projects/{loose['id']}?lang=en").json()
        part_entry = next((p for p in details["parts"] if p["part_id"] == part_id), None)
        assert part_entry is not None
        assert part_entry["quantity_available"] == 23

        assert client.delete(f"/api/projects/{loose['id']}").status_code == 400
        assert client.put(f"/api/projects/{loose['id']}", json={"name": "Changed"}).status_code == 400
        assert client.post(
            f"/api/projects/{loose['id']}/add_part",
            json={"part_id": part_id, "quantity_needed": 1},
        ).status_code == 400
        assert client.post(
            f"/api/projects/{loose['id']}/update_part_quantity?part_id={part_id}&quantity_needed=1",
        ).status_code == 400
        assert client.delete(f"/api/projects/{loose['id']}/remove_part/{part_id}").status_code == 400
        db = SessionLocal()
        try:
            custom_id = db.query(Part).filter(Part.id == part_id).one().external_part_id
        finally:
            db.close()
        response = client.post("/api/inventory/add_part_to_inventory", json={
            "library_source": "custom", "external_part_id": custom_id,
            "quantity": 1, "project_ids": [loose["id"]],
        })
        assert response.status_code == 400
    finally:
        _delete_part(part_id)


def test_loose_parts_excludes_parts_linked_to_regular_projects():
    part_id = _create_custom_part("TEST_LOOSE_ASSIGNED", 5)
    project_id = client.post(
        "/api/projects/api_add", json={"name": "TEST_LOOSE_OWNER"}
    ).json()["id"]
    try:
        loose = next(
            project for project in client.get("/api/projects/").json()
            if project["system_key"] == "loose_parts"
        )
        assert client.post(
            f"/api/projects/{project_id}/add_part",
            json={"part_id": part_id, "quantity_needed": 2},
        ).status_code == 200
        details = client.get(f"/api/projects/{loose['id']}").json()
        assert not any(p["part_id"] == part_id for p in details["parts"])
    finally:
        db = SessionLocal()
        try:
            db.query(ProjectPart).filter(ProjectPart.project_id == project_id).delete()
            db.query(Project).filter(Project.id == project_id).delete()
            db.commit()
        finally:
            db.close()
        _delete_part(part_id)
