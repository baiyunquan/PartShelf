import base64
import json
import sqlite3
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.custom_component import CustomComponent
from app.models.inventory import Inventory
from app.models.part import Part
from app.models.warehouse_placement import WarehousePlacement
from app.services import warehouse_service
from app.services.warehouse_service import WarehouseService
from db.schema_migrations import initialize_main_database


PHOTO = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1kAAAAASUVORK5CYII=")


@pytest.fixture
def engine(tmp_path):
    value = create_engine(f"sqlite:///{tmp_path / 'warehouse.db'}", connect_args={"check_same_thread": False})
    initialize_main_database(value)
    yield value
    value.dispose()


def add_part(engine, name="100nF", kind="Capacitor", quantity=5, package="0603"):
    with Session(engine) as db:
        component = CustomComponent(name=name, part_type=kind, package=package)
        db.add(component)
        db.flush()
        part = Part(library_source="custom", external_part_id=str(component.id))
        db.add(part)
        db.flush()
        db.add(Inventory(part_id=part.id, quantity_available=quantity))
        part_id = part.id
        db.commit()
        return part_id


def suggest(engine, part_id, drawer_type="S"):
    with Session(engine) as db:
        return WarehouseService.suggest(db, part_id, drawer_type)


def place(engine, part_id, cabinet="BOX-000", drawer="S-01"):
    with Session(engine) as db:
        return WarehouseService.place(db, part_id, cabinet, drawer, PHOTO, "image/png")


def test_recommendation_is_read_only_and_confirmation_reuses_equivalent_group(engine):
    first = add_part(engine)
    second = add_part(engine, "0.1uF", package="0805")
    assert hasattr(WarehouseService, "suggest"), "Warehouse recommendation is missing"
    recommendation = suggest(engine, first)
    assert recommendation["recommended"]["drawer_code"] == "S-01"
    with Session(engine) as db:
        assert db.query(WarehousePlacement).count() == 0
    place(engine, first)
    assert suggest(engine, second)["recommended"]["state"] == "compatible"
    assert suggest(engine, second)["recommended"]["drawer_code"] == "S-01"
    place(engine, second)
    with Session(engine) as db:
        assert db.get(Part, second).storage_location == "BOX-000 / S-01"
        assert db.query(WarehousePlacement).count() == 2


def test_type_filter_and_conflicting_confirmation(engine):
    capacitor = add_part(engine)
    resistor = add_part(engine, "10kΩ", "Resistor")
    assert suggest(engine, capacitor, "L")["recommended"]["drawer_code"] == "L-01"
    place(engine, capacitor)
    assert suggest(engine, resistor)["recommended"]["drawer_code"] == "S-02"
    with pytest.raises(HTTPException) as error:
        place(engine, resistor)
    assert error.value.status_code == 409
    with Session(engine) as db:
        assert db.get(WarehousePlacement, resistor) is None
        assert db.get(Part, resistor).storage_location is None


def test_photo_and_positive_quantity_are_required(engine):
    part_id = add_part(engine, quantity=0)
    with pytest.raises(HTTPException) as error:
        place(engine, part_id)
    assert error.value.status_code == 409
    part_id = add_part(engine)
    with Session(engine) as db, pytest.raises(HTTPException) as error:
        WarehouseService.place(db, part_id, "BOX-000", "S-01", b"", "image/png")
    assert error.value.status_code == 422


def test_idempotence_zero_stock_and_release_reuse(engine):
    part_id = add_part(engine)
    place(engine, part_id)
    assert place(engine, part_id)["already_placed"] is True
    with pytest.raises(HTTPException):
        place(engine, part_id, drawer="S-02")
    with Session(engine) as db:
        db.get(Inventory, part_id).quantity_available = 0
        db.commit()
    other = add_part(engine, "1uF")
    assert suggest(engine, other)["recommended"]["drawer_code"] == "S-02"
    with Session(engine) as db:
        WarehouseService.remove(db, part_id)
    assert suggest(engine, other)["recommended"]["drawer_code"] == "S-01"
    with Session(engine) as db:
        assert db.get(Part, part_id).storage_location is None
        assert WarehouseService.remove(db, part_id)["removed"] is False


def test_mixed_legacy_drawer_is_preserved_and_excluded(engine):
    first = add_part(engine)
    second = add_part(engine, "10kΩ", "Resistor")
    third = add_part(engine)
    with Session(engine) as db:
        for part_id in (first, second):
            db.add(WarehousePlacement(part_id=part_id, cabinet_id="BOX-000", drawer_code="S-01",
                                      photo_data=PHOTO, photo_mime_type="image/png"))
        db.commit()
    assert suggest(engine, third)["recommended"]["drawer_code"] == "S-02"
    with Session(engine) as db:
        assert db.get(WarehousePlacement, first).photo_data == PHOTO


def test_concurrent_incompatible_claims_have_one_winner(engine):
    ids = [add_part(engine), add_part(engine, "1uF")]
    def claim(part_id):
        try:
            place(engine, part_id)
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, ids)) == [200, 409]
    with Session(engine) as db:
        assert db.query(WarehousePlacement).count() == 1


def test_concurrent_duplicate_confirmation_has_one_placement(engine):
    part_id = add_part(engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: place(engine, part_id), range(2)))
    assert sum(bool(result["already_placed"]) for result in results) == 1


def test_no_compatible_drawer_returns_reason(engine, monkeypatch):
    part_id = add_part(engine)
    place(engine, part_id)
    config = warehouse_service.get_cabinet_config()
    config = config[:1]
    config[0]["drawerGroups"] = config[0]["drawerGroups"][:1]
    config[0]["drawerGroups"][0]["drawers"] = config[0]["drawerGroups"][0]["drawers"][:1]
    monkeypatch.setattr(warehouse_service, "get_cabinet_config", lambda: config)
    result = suggest(engine, add_part(engine, "1uF"))
    assert result["recommended"] is None
    assert result["reason"] == "no_available_drawer"


def test_delete_part_does_not_leave_cached_reservation(engine):
    part_id = add_part(engine)
    place(engine, part_id)
    with Session(engine) as db:
        db.delete(db.get(Part, part_id))
        db.commit()
    assert suggest(engine, add_part(engine, "1uF"))["recommended"]["drawer_code"] == "S-01"


def test_failed_write_rolls_back_placement_and_location(engine, monkeypatch):
    part_id = add_part(engine)
    with Session(engine) as db:
        monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("write failed")))
        with pytest.raises(RuntimeError):
            WarehouseService.place(db, part_id, "BOX-000", "S-01", PHOTO, "image/png")
    with Session(engine) as db:
        assert db.get(WarehousePlacement, part_id) is None
        assert db.get(Part, part_id).storage_location is None


@pytest.mark.parametrize("kind,a,b", [
    ("Capacitor", "100nF", "0.1uF"),
    ("Resistor", "4k7", "4700Ω"),
    ("Inductor", "1000uH", "1mH"),
    ("IC", "LM358DR", "LM358P"),
])
def test_grouping_equivalence(kind, a, b):
    from app.services.warehouse_grouping import group_for_record
    first = group_for_record("custom", "1", {"name": a, "part_type": kind, "package": "0603"})
    second = group_for_record("altium", "2", {"name": b, "part_type": kind, "package": "0805"})
    assert first.key == second.key


@pytest.mark.parametrize("a,b", [
    ({"part_type": "Resistor", "name": "1mΩ"}, {"part_type": "Resistor", "name": "1MΩ"}),
    ({"part_type": "Capacitor", "name": "1uF"}, {"part_type": "Inductor", "name": "1uH"}),
    ({"part_type": "IC", "name": "LM358XYZ"}, {"part_type": "IC", "name": "LM358"}),
    ({"part_type": "Screw", "name": "M3"}, {"part_type": "Nut", "name": "M3"}),
    ({"part_type": "IC", "name": "CHIP123", "description": "100nF"}, {"part_type": "Capacitor", "name": "100nF"}),
    ({"part_type": "Capacitor", "description": "1uF / 2uF"}, {"part_type": "Capacitor", "name": "1uF"}),
    ({"part_type": "Custom", "name": "unknown"}, {"part_type": "Custom", "name": "unknown"}),
])
def test_grouping_does_not_guess(a, b):
    from app.services.warehouse_grouping import group_for_record
    assert group_for_record("custom", "1", a).key != group_for_record("custom", "2", b).key


def test_local_native_parameters_ignore_search_aliases(engine, tmp_path, monkeypatch):
    from app.services import external_library_service as catalog
    from app.services.warehouse_grouping import group_for_part, group_for_record
    path = tmp_path / "catalog.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE jlc_components (lcsc INTEGER PRIMARY KEY, category TEXT, mfr TEXT, attributes TEXT)")
        connection.execute("INSERT INTO jlc_components VALUES (1, 'Capacitors', 'MODEL1', ?)",
                           (json.dumps({"Capacitance": "100nF"}),))
        connection.execute("CREATE TABLE part_search_aliases (alias TEXT)")
        connection.execute("INSERT INTO part_search_aliases VALUES ('1uF')")
    monkeypatch.setattr(catalog, "JLCPARTS_DB_PATH", path)
    with Session(engine) as db:
        part = Part(library_source="jlcparts", external_part_id="C1")
        assert group_for_part(db, part).key == group_for_record("custom", "2", {"part_type": "Capacitor", "name": "100nF"}).key


def test_grouping_reads_custom_record_from_current_session(engine):
    from app.services.warehouse_grouping import group_for_part, group_for_record
    with Session(engine) as db:
        component = CustomComponent(name="100nF", part_type="Capacitor")
        db.add(component)
        db.flush()
        part = Part(library_source="custom", external_part_id=str(component.id))
        assert group_for_part(db, part).key == group_for_record("custom", "other", {"part_type": "Capacitor", "name": "0.1uF"}).key


def test_drawer_seeding_is_idempotent_and_preserves_metadata(engine):
    from app.models.warehouse_drawer import WarehouseDrawer
    with Session(engine) as db:
        drawer = db.get(WarehouseDrawer, ("BOX-000", "S-01"))
        drawer.group_key = "preserve"
        db.commit()
    initialize_main_database(engine)
    with Session(engine) as db:
        assert db.query(WarehouseDrawer).count() == 117
        assert db.get(WarehouseDrawer, ("BOX-000", "S-01")).group_key == "preserve"


def test_removal_keeps_manual_location_and_shared_drawer(engine):
    first, second = add_part(engine), add_part(engine)
    place(engine, first)
    place(engine, second)
    with Session(engine) as db:
        db.get(Part, first).storage_location = "Manual label"
        db.commit()
        WarehouseService.remove(db, first)
        assert db.get(Part, first).storage_location == "Manual label"
    assert suggest(engine, add_part(engine, "1uF"))["recommended"]["drawer_code"] == "S-02"


@pytest.fixture
def api(engine):
    from fastapi.testclient import TestClient
    from app.main import app
    from db.database import get_db
    def get_test_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = get_test_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_placement_api_round_trip(engine, api):
    part_id = add_part(engine)
    prefix = f"/api/warehouse/parts/{part_id}"
    assert api.get(prefix + "/suggestion?drawer_type=S").status_code == 200
    assert api.get(prefix + "/suggestion?drawer_type=X").status_code == 422
    data = {"cabinet_id": "BOX-000", "drawer_code": "S-01"}
    assert api.post(prefix + "/placement", data=data).status_code == 422
    assert api.post(prefix + "/placement", data=data, files={"photo": ("fake.png", b"fake", "image/png")}).status_code == 422
    response = api.post(prefix + "/placement", data=data, files={"photo": ("photo.png", PHOTO, "image/png")})
    assert response.status_code == 200
    assert response.json()["already_placed"] is False
    assert api.get(prefix + "/photo").content == PHOTO
    inventory = api.get(f"/api/inventory/get_part_by_id?part_id={part_id}").json()
    assert inventory["warehouse_status"] == "in_warehouse"
    assert inventory["storage_location"] == "BOX-000 / S-01"
    assert api.get(prefix + "/suggestion?drawer_type=S").json()["reason"] == "already_placed"
    assert api.delete(prefix + "/placement").json()["removed"] is True
    assert api.get(prefix + "/photo").status_code == 404


def test_warehouse_form_and_entry_points():
    root = Path(__file__).resolve().parents[1]
    warehouse = (root / "templates/warehouse.html").read_text()
    assert 'id="warehouse-placement-form"' in warehouse
    assert 'id="warehouse-photo"' in warehouse
    assert 'src="/static/js/warehouse_placement.js"' in warehouse
    assert "/warehouse?part_id=" in (root / "static/js/inventory.js").read_text()
    assert 'id="warehouse-placement-link"' in (root / "templates/component_details.html").read_text()
    for lang in ("zh", "en"):
        bundle = json.loads((root / f"app/i18n/locales/{lang}.json").read_text())
        assert bundle["warehouse"]["placement_confirm"]
        assert bundle["warehouse"]["remove_confirm"]


@pytest.mark.parametrize("record", [
    {"category": "Power Management (PMIC)", "mfr": "LM358DR", "capacitance": "100nF"},
    {"part_type": "IC", "name": "LM358 DR"},
])
def test_native_chip_categories_and_model_spacing(record):
    from app.services.warehouse_grouping import group_for_record
    group = group_for_record("jlcparts", "1", record)
    assert group.kind == "chip"
    assert group.label == "LM358"


def test_specific_mechanical_title_recognizes_mechanical_spec(engine):
    from app.services.warehouse_grouping import group_for_record
    group = group_for_record("fasteners", "1", {
        "category_group": "Special Head Bolts", "category_group_zh": "特殊头型螺栓/螺钉",
        "standard_name": "Eye bolts",
    })
    assert group.kind == "mechanical"
    assert group.label == "Eye bolts"


def test_mysql_photo_type_can_store_full_upload():
    from sqlalchemy.dialects import mysql
    column_type = WarehousePlacement.__table__.c.photo_data.type
    assert column_type.compile(dialect=mysql.dialect()) in {"MEDIUMBLOB", "LONGBLOB"}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_warehouse_placement_interactions():
    result = subprocess.run(["node", "--test", "tests/js/warehouse_placement.test.js"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_recommendation_and_contents_do_not_read_photo_blobs(engine):
    placed, pending = add_part(engine), add_part(engine)
    place(engine, placed)
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as db:
            assert WarehouseService.suggest(db, pending, "S")["recommended"]["state"] == "compatible"
            assert WarehouseService.get_contents(db)["cabinets"][0]["drawerGroups"][0]["drawers"][0]["parts"][0]["id"] == placed
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    placement_reads = [sql for sql in statements if "FROM warehouse_placements" in sql]
    assert placement_reads
    assert all("photo_data" not in sql for sql in placement_reads)


def test_mysql_allocation_requests_fresh_read_committed_transaction():
    # The driver boundary is exercised without requiring an external server.
    from unittest.mock import Mock
    db = Mock(spec=Session)
    db.get_bind.return_value.dialect.name = "mysql"
    db.in_transaction.return_value = False
    WarehouseService._begin_write(db)
    db.connection.assert_called_once_with(execution_options={"isolation_level": "READ COMMITTED"})
