import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.main import app
from app.models.custom_component import CustomComponent
from app.models.inventory import Inventory
from app.models.part import Part
from app.models.project import Project
from app.models.project_part import ProjectPart
from app.schemas.inventory import PartToInventoryAdd, PartInventoryQuantityUpdate
from app.services.bom_service import analyze_bom_matching, execute_bom_import
from app.services.inventory_service import InventoryService
from db.database import Base


@pytest.fixture
def inventory_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'partshelf.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def screw_row(**overrides):
    row = {
        "supplier_part": "",
        "quantity": 4,
        "designator": "SCREW1",
        "footprint": "M2 screw",
        "comment": "M2 screw",
        "value": "M2 screw",
        "primary_category": "",
        "secondary_category": "",
        "pin_count": "1",
        "manufacturer_part": "",
        "manufacturer": "",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("M2 × 8 mm", {"nominal": "M2", "length": "8"}),
        ("1/4-20 x 1", {"nominal": "1/4in", "length": "1in"}),
        ("1/4-20 x 8 mm", {"nominal": "1/4in", "length": "8"}),
    ],
)
def test_fastener_dimension_parser_normalizes_metric_and_imperial_notation(text, expected):
    from app.services.bom_matcher import parse_fastener_text

    assert parse_fastener_text(text) == expected


def test_custom_heat_insert_variants_hydrate_distinct_rows_and_inventory_references(tmp_path, monkeypatch, inventory_db):
    import shutil
    from app.services import external_library_service as lib_svc
    from app.services.fastener_variant_service import build_custom_fastener_variant_id, get_fastener_variant

    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)
    first = lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.5})
    second = lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.6})

    first_id = build_custom_fastener_variant_id("IUTHeatInsert", first["row_key"])
    second_id = build_custom_fastener_variant_id("IUTHeatInsert", second["row_key"])
    assert first_id.startswith("fastener:v2/")
    assert first_id != second_id
    first_variant = get_fastener_variant(first_id)
    second_variant = get_fastener_variant(second_id)
    assert first_variant["selected_variant"]["dimensions"]["ExtDia"] == 5.5
    assert second_variant["selected_variant"]["dimensions"]["ExtDia"] == 5.6

    first_part = InventoryService.add_part_to_inventory(inventory_db, PartToInventoryAdd(
        library_source="fasteners", external_part_id=first_id, quantity=1
    ))
    second_part = InventoryService.add_part_to_inventory(inventory_db, PartToInventoryAdd(
        library_source="fasteners", external_part_id=second_id, quantity=1
    ))
    assert first_part.external_part_id == first_id
    assert second_part.external_part_id == second_id
    assert first_part.name != second_part.name
    assert "5.5" in first_part.name
    assert "5.6" in second_part.name


def test_custom_flat_head_variant_carries_custom_length(tmp_path, monkeypatch):
    import shutil
    from app.services import external_library_service as lib_svc
    from app.services.fastener_variant_service import build_custom_fastener_variant_id, get_fastener_variant

    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)
    spec = lib_svc.append_fastener_spec("ISO10642", "M3", {"P": 0.5}, length="4.5")

    variant = get_fastener_variant(build_custom_fastener_variant_id("ISO10642", spec["row_key"]))

    assert variant is not None
    assert variant["selected_variant"]["nominal"] == "M3"
    assert variant["selected_variant"]["length"] == "4.5"


def test_custom_flat_head_bom_requires_matching_nominal_and_custom_length(tmp_path, monkeypatch):
    import shutil
    from app.services import external_library_service as lib_svc
    from app.services.bom_matcher import BomMatcher

    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)
    lib_svc.append_fastener_spec("ISO10642", "M3", {"P": 0.5}, length="4.5")
    matcher = BomMatcher()
    try:
        matched = matcher.fastener_match(screw_row(
            value="ISO10642 M3x4.5 countersunk screw",
            comment="flat head screw M3 x 4.5 mm",
            footprint="M3 countersunk screw",
            mechanical_standard="ISO10642",
        ))
        mismatch = matcher.fastener_match(screw_row(
            value="ISO10642 M3x4.6 countersunk screw",
            comment="flat head screw M3 x 4.6 mm",
            footprint="M3 countersunk screw",
            mechanical_standard="ISO10642",
        ))
        without_standard = matcher.fastener_match(screw_row(
            value="M3x4.5 countersunk screw",
            comment="flat head screw M3 x 4.5 mm",
            footprint="M3 countersunk screw",
        ))
    finally:
        matcher.close()

    assert matched["reason"] == "dimension_match"
    assert matched["items"][0]["external_part_id"].startswith("fastener:v2/")
    assert mismatch["reason"] == "no_dimension_match"
    assert mismatch["items"] == []
    from app.i18n.fastener_aliases import aliases_for_standard
    assert without_standard["items"]
    assert all("沉头螺钉" in aliases_for_standard(item["standard_code"]) for item in without_standard["items"])


def test_heat_insert_parser_extracts_thread_outer_diameter_and_length():
    from app.services.bom_matcher import parse_heat_insert_text

    assert parse_heat_insert_text("铜土八热熔螺母，规格：M3*5.5*4") == {
        "nominal": "M3", "outer_diameter": "5.5", "length": "4"
    }


def test_custom_heat_insert_bom_matches_all_three_dimensions(tmp_path, monkeypatch):
    import shutil
    from app.services import external_library_service as lib_svc
    from app.services.bom_matcher import BomMatcher

    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)
    lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.5})
    row = screw_row(
        value="M3*5.5*4",
        comment="热熔铜螺母 规格：M3*5.5*4",
        footprint="M3 热熔螺母",
        mechanical_nominal="M3",
        mechanical_length="4",
    )

    matcher = BomMatcher()
    try:
        result = matcher.fastener_match(row)
    finally:
        matcher.close()

    assert result["reason"] == "dimension_match"
    assert len(result["items"]) == 1
    assert result["items"][0]["external_part_id"].startswith("fastener:v2/")
    assert result["items"][0]["dimensions"]["ExtDia"] == 5.5


def test_custom_heat_insert_xlsx_preview_and_import_keep_v2_reference(tmp_path, monkeypatch, inventory_db):
    import shutil
    from app.services import external_library_service as lib_svc

    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)
    lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.5})
    row = screw_row(
        value="M3*5.5*4",
        comment="热熔铜螺母 规格：M3*5.5*4",
        footprint="M3 热熔螺母",
        mechanical_nominal="M3",
        mechanical_length="4",
    )

    preview = analyze_bom_matching([row], inventory_db)
    item = preview["items"][0]
    assert item["status"] == "matched_library"
    assert item["selected"] is True
    assert item["external_part_id"].startswith("fastener:v2/")

    imported = execute_bom_import(
        db=inventory_db,
        target_type="new",
        project_name="Custom fastener BOM",
        project_description=None,
        existing_project_id=None,
        quantity_strategy="add",
        items=[item],
    )

    assert imported["imported_parts_count"] == 1
    part = inventory_db.query(Part).filter(Part.library_source == "fasteners").one()
    assert part.external_part_id == item["external_part_id"]


@pytest.mark.parametrize(
    ("value", "expected_reason", "expected_missing"),
    [
        ("M3*5.6*4", "no_dimension_match", []),
        ("M3*5.5", "incomplete_dimensions", ["length"]),
    ],
)
def test_heat_insert_bom_rejects_conflicting_or_incomplete_dimensions(
    tmp_path, monkeypatch, value, expected_reason, expected_missing
):
    import shutil
    from app.services import external_library_service as lib_svc
    from app.services.bom_matcher import BomMatcher

    db_path = tmp_path / "fasteners.db"
    shutil.copy2(lib_svc.FASTENERS_DB_PATH, db_path)
    monkeypatch.setattr(lib_svc, "FASTENERS_DB_PATH", db_path)
    lib_svc.append_fastener_spec("IUTHeatInsert", "M3", {"Length": 4, "ExtDia": 5.5})
    row = screw_row(
        value=value, comment="热熔铜螺母", footprint="M3 热熔螺母",
        mechanical_standard="IUTHeatInsert",
    )

    matcher = BomMatcher()
    try:
        result = matcher.fastener_match(row)
    finally:
        matcher.close()

    assert result["reason"] == expected_reason
    assert result["missing_dimensions"] == expected_missing
    if expected_reason != "dimension_match":
        assert result["items"] == []


def test_incomplete_m2_screw_has_no_bindable_fastener_candidates(inventory_db):
    item = analyze_bom_matching([screw_row()], inventory_db)["items"][0]

    assert item["status"] == "unmatched"
    assert item["match_reason"] == "incomplete_dimensions"
    assert "length" in item["missing_dimensions"]
    assert item["suggestions"] == []
    assert item["library_source"] is None


def test_complete_iso4762_m2x8_row_matches_by_dimensions(inventory_db):
    row = screw_row(
        value="ISO4762 M2x8",
        comment="ISO 4762 M2 x 8 mm socket screw, stainless steel, class 12.9",
        manufacturer="Different manufacturer",
    )

    item = analyze_bom_matching([row], inventory_db)["items"][0]

    assert item["status"] == "matched_library"
    assert item["library_source"] == "fasteners"
    assert item["external_part_id"] == "fastener:v1/ISO4762/M2/8"
    assert item["selected"] is True


def test_complete_imperial_fastener_notation_matches_standard_dimensions(inventory_db):
    item = analyze_bom_matching(
        [screw_row(
            value="ASME B18.2.1.6 1/4-20 x 1",
            comment="1/4-20 x 1 socket screw",
            footprint="1/4-20 screw",
        )],
        inventory_db,
    )["items"][0]

    assert item["status"] == "matched_library"
    assert item["library_source"] == "fasteners"
    assert item["external_part_id"] == "fastener:v1/ASMEB18.2.1.6/1%2F4in/1in"


def test_fastener_manual_search_accepts_ascii_x_dimension_notation():
    from app.services.bom_matcher import BomMatcher

    matcher = BomMatcher()
    try:
        result = matcher.fastener_match(
            screw_row(value="ISO4762 M2x8", comment="ISO4762 M2x8"),
            query="M2x8",
        )
    finally:
        matcher.close()

    assert result["items"]
    assert result["items"][0]["external_part_id"] == "fastener:v1/ISO4762/M2/8"


def test_complete_dimensions_with_ambiguous_standard_offer_review_candidates():
    from app.services.bom_matcher import BomMatcher

    matcher = BomMatcher()
    try:
        result = matcher.fastener_match(
            screw_row(value="M2x8 screw", comment="M2x8 screw")
        )
    finally:
        matcher.close()

    assert result["reason"] == "ambiguous_dimensions"
    assert "standard_or_head_geometry" in result["missing_dimensions"]
    assert result["items"]
    assert all(item["library_source"] == "fasteners" for item in result["items"])


def test_unlisted_fastener_length_does_not_match(inventory_db):
    item = analyze_bom_matching(
        [screw_row(value="ISO4762 M2x9.5", comment="ISO4762 M2x9.5")], inventory_db
    )["items"][0]

    assert item["status"] == "unmatched"
    assert item["match_reason"] == "no_dimension_match"
    assert item["suggestions"] == []


def test_conflicting_fastener_dimensions_are_not_auto_matched(inventory_db):
    item = analyze_bom_matching(
        [screw_row(value="ISO4762 M2x8", comment="ISO4762 M2x10")], inventory_db
    )["items"][0]

    assert item["status"] == "unmatched"
    assert "dimensions" in item["conflicts"]
    assert item["suggestions"] == []


def test_fastener_inventory_reference_hydrates_specific_variant(inventory_db):
    part = InventoryService.add_part_to_inventory(
        inventory_db,
        PartToInventoryAdd(
            library_source="fasteners",
            external_part_id="fastener:v1/ISO4762/M2/8",
            quantity=12,
            storage_location="Drawer 2",
        ),
    )

    assert part.library_source == "fasteners"
    assert part.external_part_id == "fastener:v1/ISO4762/M2/8"
    assert part.quantity == 12
    details = InventoryService.get_part_by_id(inventory_db, part.id)
    assert "ISO4762" in details.name
    assert details.external_details["selected_variant"]["nominal"] == "M2"
    assert details.external_details["selected_variant"]["length"] == "8"


@pytest.mark.parametrize(
    "external_part_id",
    [
        "fastener:v1/NO_SUCH_STANDARD/M2/8",
        "fastener:v1/ISO4762/M2/-",
        "fastener:v1/ISO4762/M2/9",
    ],
)
def test_inventory_rejects_unknown_standard_missing_length_and_unlisted_length(inventory_db, external_part_id):
    with pytest.raises(HTTPException) as exc_info:
        InventoryService.add_part_to_inventory(
            inventory_db,
            PartToInventoryAdd(
                library_source="fasteners",
                external_part_id=external_part_id,
                quantity=1,
            ),
        )

    assert exc_info.value.status_code == 404


def test_fastener_inventory_quantity_can_be_updated(inventory_db):
    part = InventoryService.add_part_to_inventory(
        inventory_db,
        PartToInventoryAdd(
            library_source="fasteners",
            external_part_id="fastener:v1/ISO4762/M2/8",
            quantity=12,
        ),
    )

    updated = InventoryService.update_inventory_quantity(
        inventory_db, PartInventoryQuantityUpdate(part_id=part.id, quantity=3)
    )

    assert updated.updatedQuantity == 15


def test_fastener_search_target_is_available_for_inventory_lookup(monkeypatch):
    from app.api import library_api_routes

    monkeypatch.setattr(
        library_api_routes.lib_svc,
        "query_fasteners",
        lambda **kwargs: {"items": [{"standard_code": "ISO4762"}], "total": 1},
    )
    client = TestClient(app)

    response = client.get("/api/libraries/search?q=M2&target=fasteners")

    assert response.status_code == 200
    assert response.json()["fasteners"]["items"] == [{"standard_code": "ISO4762"}]


def test_fastener_search_is_included_in_global_library_search(monkeypatch):
    from app.api import library_api_routes

    monkeypatch.setattr(
        library_api_routes.lib_svc,
        "search_all_libraries",
        lambda *args, **kwargs: {"jlcparts": [], "altium": [], "kicad": []},
    )
    monkeypatch.setattr(
        library_api_routes.lib_svc,
        "query_fasteners",
        lambda **kwargs: {"items": [{"standard_code": "ISO4762"}], "total": 1},
    )

    response = TestClient(app).get("/api/libraries/search?q=ISO4762&target=all")

    assert response.status_code == 200
    assert response.json()["fasteners"]["items"][0]["standard_code"] == "ISO4762"


def test_bom_import_creates_inventory_reference_for_matched_fastener(inventory_db):
    item = analyze_bom_matching(
        [screw_row(value="ISO4762 M2x8", comment="ISO4762 M2x8")], inventory_db
    )["items"][0]
    item["quantity"] = 4

    result = execute_bom_import(
        db=inventory_db,
        target_type="new",
        project_name="Fastener BOM",
        project_description=None,
        existing_project_id=None,
        quantity_strategy="overwrite",
        items=[item],
    )

    part = inventory_db.query(Part).filter_by(library_source="fasteners").one()
    stock = inventory_db.query(Inventory).filter_by(part_id=part.id).one()
    project_part = inventory_db.query(ProjectPart).filter_by(part_id=part.id).one()
    assert result["imported_parts_count"] == 1
    assert part.external_part_id == "fastener:v1/ISO4762/M2/8"
    assert stock.quantity_available == 0
    assert project_part.quantity_needed == 4


def test_bom_import_allows_user_confirmed_ambiguous_fastener_candidate(inventory_db):
    row = screw_row(value="M2x8 screw", comment="M2x8 screw")
    item = analyze_bom_matching([row], inventory_db)["items"][0]

    assert item["status"] == "unmatched"
    assert len(item["suggestions"]) > 1
    candidate = item["suggestions"][0]
    item.update(
        library_source=candidate["library_source"],
        external_part_id=candidate["external_part_id"],
        matched_part_name=candidate["name"],
        status="matched_library",
        selected=True,
        confirmed_match=True,
    )

    result = execute_bom_import(
        db=inventory_db,
        target_type="new",
        project_name="Confirmed Fastener BOM",
        project_description=None,
        existing_project_id=None,
        quantity_strategy="overwrite",
        items=[item],
    )

    assert result["imported_parts_count"] == 1
    assert inventory_db.query(Part).filter_by(
        library_source="fasteners", external_part_id=candidate["external_part_id"]
    ).one()


def test_import_rejects_fastener_variant_when_bom_dimensions_are_incomplete(inventory_db):
    item = screw_row()
    item.update(
        row_index=1,
        library_source="fasteners",
        external_part_id="fastener:v1/ISO4762/M2/8",
        selected=True,
        confirmed_match=True,
    )

    with pytest.raises(ValueError, match="dimensions do not match"):
        execute_bom_import(
            db=inventory_db,
            target_type="new",
            project_name="Incomplete Fastener BOM",
            project_description=None,
            existing_project_id=None,
            quantity_strategy="overwrite",
            items=[item],
        )

    assert inventory_db.query(Project).count() == 0
