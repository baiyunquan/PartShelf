from sqlalchemy.orm import Session, joinedload

from app.models.part import Part
from app.models.warehouse_placement import WarehousePlacement
from app.services.external_library_service import resolve_part_summary
from app.warehouse_config import get_cabinet_config


class WarehouseService:
    @staticmethod
    def get_contents(db: Session, lang: str = "zh") -> dict:
        cabinets = get_cabinet_config()
        drawers = {
            (cabinet["id"], drawer["code"]): drawer
            for cabinet in cabinets
            for group in cabinet["drawerGroups"]
            for drawer in group["drawers"]
        }

        placements = db.query(WarehousePlacement).options(
            joinedload(WarehousePlacement.part).joinedload(Part.inventory)
        ).order_by(WarehousePlacement.cabinet_id, WarehousePlacement.drawer_code,
                   WarehousePlacement.part_id).all()
        for placement in placements:
            drawer = drawers.get((placement.cabinet_id, placement.drawer_code))
            if drawer is None:
                continue
            part = placement.part
            if part is None:
                continue
            summary = resolve_part_summary(part.library_source, part.external_part_id, lang)
            drawer.setdefault("parts", []).append({
                "id": part.id,
                "library_source": part.library_source,
                "external_part_id": part.external_part_id,
                "name": summary.get("name") or f"Part #{part.id}",
                "manufacturer": summary.get("manufacturer"),
                "package": summary.get("package"),
                "part_type": summary.get("part_type"),
                "quantity": part.inventory.quantity_available if part.inventory else 0,
                "photo_url": f"/api/warehouse/parts/{part.id}/photo",
            })

        for drawer in drawers.values():
            drawer.setdefault("parts", [])
            drawer["part_count"] = len(drawer["parts"])
            drawer["available_quantity"] = sum(part["quantity"] for part in drawer["parts"])

        unplaced_count = db.query(Part).filter(~Part.warehouse_placement.has()).count()
        return {"cabinets": cabinets, "unplaced_part_count": unplaced_count}

    @staticmethod
    def get_photo(db: Session, part_id: int):
        return db.query(WarehousePlacement).filter(
            WarehousePlacement.part_id == part_id
        ).first()
