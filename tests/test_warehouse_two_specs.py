from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
import json
import shutil
import subprocess

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.inventory import Inventory
from app.models.part import Part
from app.models.warehouse_placement import WarehousePlacement
from app.services.warehouse_grouping import group_for_record
from app.services.warehouse_service import WarehouseService
from tests.test_warehouse_allocation import PHOTO, add_part, api, engine, place, suggest


def duplicate_part(engine, part_id):
    with Session(engine) as db:
        original = db.get(Part, part_id)
        duplicate = Part(library_source=original.library_source, external_part_id=original.external_part_id)
        db.add(duplicate)
        db.flush()
        db.add(Inventory(part_id=duplicate.id, quantity_available=3))
        new_id = duplicate.id
        db.commit()
        return new_id


def test_any_two_mechanical_specs_share_drawer_but_third_is_rejected(engine):
    screw = add_part(engine, "M3 x 8", "Screw")
    nut = add_part(engine, "M4", "Nut")
    washer = add_part(engine, "M4", "Washer")
    place(engine, screw)
    assert suggest(engine, nut)["recommended"]["drawer_code"] == "S-01"
    place(engine, nut)
    assert suggest(engine, washer)["recommended"]["drawer_code"] == "S-02"
    with pytest.raises(HTTPException) as error:
        place(engine, washer)
    assert error.value.status_code == 409
    with Session(engine) as db:
        assert db.query(WarehousePlacement).count() == 2


def test_duplicate_spec_does_not_use_another_slot_and_is_preferred(engine):
    first = add_part(engine, "M3", "Screw")
    second = add_part(engine, "M4", "Nut")
    duplicate = duplicate_part(engine, first)
    place(engine, first, drawer="S-02")
    # Matching an occupied spec outranks the earlier empty drawer.
    assert suggest(engine, duplicate)["recommended"]["drawer_code"] == "S-02"
    place(engine, second, drawer="S-02")
    place(engine, duplicate, drawer="S-02")
    with Session(engine) as db:
        assert db.query(WarehousePlacement).count() == 3


def test_matching_spec_outranks_a_drawer_that_can_accept_second_spec(engine):
    screw = add_part(engine, "M3", "Screw")
    nut = add_part(engine, "M4", "Nut")
    duplicate = duplicate_part(engine, nut)
    place(engine, screw)
    place(engine, nut, drawer="S-02")
    assert suggest(engine, duplicate)["recommended"]["drawer_code"] == "S-02"


def test_removal_releases_spec_slot_but_zero_stock_does_not(engine):
    first = add_part(engine, "M3", "Screw")
    second = add_part(engine, "M4", "Nut")
    third = add_part(engine, "M4", "Washer")
    place(engine, first)
    place(engine, second)
    with Session(engine) as db:
        db.get(Inventory, second).quantity_available = 0
        db.commit()
    assert suggest(engine, third)["recommended"]["drawer_code"] == "S-02"
    with Session(engine) as db:
        WarehouseService.remove(db, second)
    assert suggest(engine, third)["recommended"]["drawer_code"] == "S-01"


def test_old_three_spec_drawer_is_preserved_and_excluded(engine):
    ids = [add_part(engine, str(index), "Mechanical") for index in range(3)]
    with Session(engine) as db:
        for part_id in ids:
            db.add(WarehousePlacement(part_id=part_id, cabinet_id="BOX-000", drawer_code="S-01",
                                      photo_data=PHOTO, photo_mime_type="image/png"))
        db.commit()
    assert suggest(engine, duplicate_part(engine, ids[0]))["recommended"]["drawer_code"] == "S-02"
    with Session(engine) as db:
        assert db.query(WarehousePlacement).count() == 3


def test_mechanical_does_not_mix_with_electronics(engine):
    capacitor = add_part(engine)
    screw = add_part(engine, "M3", "Screw")
    place(engine, capacitor)
    assert suggest(engine, screw)["recommended"]["drawer_code"] == "S-02"
    with pytest.raises(HTTPException):
        place(engine, screw)


def test_concurrent_claims_for_second_spec_have_one_winner(engine):
    first = add_part(engine, "M3", "Screw")
    candidates = [add_part(engine, "M4", "Nut"), add_part(engine, "M4", "Washer")]
    place(engine, first)
    def claim(part_id):
        try:
            place(engine, part_id)
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, candidates)) == [200, 409]


def test_fasteners_and_unknown_mechanical_families_use_complete_spec_identity():
    first = group_for_record("fasteners", "fastener:v1/DIN912/M3/8", {})
    second = group_for_record("fasteners", "fastener:v1/DIN7991/M3/8", {})
    assert first.kind == second.kind == "mechanical"
    assert first.key != second.key
    assert group_for_record("custom", "1", {"part_type": "Mechanical", "name": "unknown size"}).kind == "mechanical"


def test_electrical_category_with_mechanical_word_keeps_electrical_group():
    group = group_for_record("custom", "1", {
        "part_type": "Capacitor",
        "category": "Screw Terminal Capacitors",
        "reference": "C",
        "value": "100uF",
    })
    assert group.kind == "capacitance"
    value_only = group_for_record("custom", "3", {
        "category": "Screw Terminal",
        "name": "100uF",
    })
    assert value_only.kind == "capacitance"
    chip = group_for_record("custom", "2", {
        "category": "Hardware Security ICs",
        "reference": "U",
        "name": "ATECC608A",
    })
    assert chip.kind == "chip"


def test_preview_is_read_only_defaults_small_and_reports_zero_stock(engine, api):
    part_id = add_part(engine, "M3", "Screw")
    with Session(engine) as db:
        external_id = db.get(Part, part_id).external_part_id
    url = f"/api/warehouse/suggestion?library_source=custom&external_part_id={external_id}"
    response = api.get(url)
    assert response.status_code == 200
    assert response.json()["drawer_type"] == "S"
    assert response.json()["recommended"]["drawer_code"] == "S-01"
    assert api.get(url + "&quantity=0").json()["reason"] == "no_stock"
    assert api.get(url + "&drawer_type=L").json()["recommended"]["drawer_code"] == "L-01"
    assert api.get(f"/api/warehouse/parts/{part_id}/suggestion").json()["drawer_type"] == "S"
    assert api.get(url + "&quantity=-1").status_code == 422
    assert api.get(url + "&drawer_type=X").status_code == 422
    assert api.get("/api/warehouse/suggestion?library_source=unknown&external_part_id=1").status_code == 422
    assert api.get("/api/warehouse/suggestion?library_source=custom&external_part_id=99999").status_code == 404
    with Session(engine) as db:
        assert db.query(Part).count() == 1
        assert db.query(WarehousePlacement).count() == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
@pytest.mark.parametrize("name", ["component_links", "inventory_recommendation"])
def test_component_addition_javascript(name):
    result = subprocess.run(["node", f"tests/js/{name}.test.js"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = {}
        self.sources = []
        self.translations = ""
        self.in_translations = False
        self.current_select = None
        self.options = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        identity = values.get("id")
        if identity:
            self.nodes[identity] = values
        if tag == "select":
            self.current_select = identity
        if tag == "option" and self.current_select:
            self.options.setdefault(self.current_select, []).append(values)
        if tag == "script":
            self.in_translations = identity == "page-translations"
            if "src" in values:
                self.sources.append(values["src"])

    def handle_data(self, data):
        if self.in_translations:
            self.translations += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_translations = False
        if tag == "select":
            self.current_select = None


@pytest.mark.parametrize("lang,continue_label", [("zh", "继续入库"), ("en", "Continue to placement")])
def test_rendered_addition_forms_load_helpers_and_default_small_drawers(api, lang, continue_label):
    inventory = FormParser()
    response = api.get(f"/inventory?lang={lang}")
    assert response.status_code == 200
    inventory.feed(response.text)
    labels = json.loads(inventory.translations)
    assert labels["warehouse_continue"] == continue_label
    assert labels["placement_no_stock"]
    assert inventory.options["inventory-drawer-type"][0]["value"] == "S"
    assert "selected" in inventory.options["inventory-drawer-type"][0]
    assert "/static/js/component_links.js" in inventory.sources
    assert "/static/js/inventory_recommendation.js" in inventory.sources
    assert inventory.sources.index("/static/js/component_links.js") < inventory.sources.index("/static/js/inventory.js")
    warehouse = FormParser()
    warehouse.feed(api.get(f"/warehouse?lang={lang}").text)
    assert [option["value"] for option in warehouse.options["warehouse-drawer-type"]] == ["S", "L"]
    assert "selected" in warehouse.options["warehouse-drawer-type"][0]
    project = FormParser()
    project.feed(api.get("/project_details?project_id=1").text)
    assert project.nodes["project-selected-part-link"]["target"] == "_blank"
    assert "/static/js/component_links.js" in project.sources
    bom = FormParser()
    bom.feed(api.get("/bom-import").text)
    assert bom.sources.index("/static/js/component_links.js") < bom.sources.index("/static/js/bom_import.js")
