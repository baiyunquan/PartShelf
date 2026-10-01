from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload, load_only

from app.models.part import Part
from app.models.inventory import Inventory
from app.models.warehouse_drawer import WarehouseDrawer
from app.models.warehouse_placement import WarehousePlacement
from app.services.external_library_service import resolve_part_summary
from app.services.warehouse_grouping import group_for_part, group_for_record, native_record
from app.warehouse_config import get_cabinet_config


class WarehouseService:
    @staticmethod
    def _drawers(drawer_type=None):
        return [
            {"cabinet_id": cabinet["id"], "drawer_code": drawer["code"],
             "drawer_type": group["typeCode"], "cabinet_number": cabinet["displayNumber"]}
            for cabinet in sorted(get_cabinet_config(), key=lambda item: item["displayNumber"])
            for group in cabinet["drawerGroups"] if drawer_type is None or group["typeCode"] == drawer_type
            for drawer in sorted(group["drawers"], key=lambda item: item["code"])
        ]

    @staticmethod
    def _part(db, part_id, lock=False):
        query = db.query(Part).filter(Part.id == part_id)
        if lock:
            query = query.populate_existing().with_for_update()
        part = query.one_or_none()
        if part is None:
            raise HTTPException(404, "Inventory part not found")
        return part

    @staticmethod
    def _occupants(db, cabinet_id=None, drawer_code=None):
        query = db.query(WarehousePlacement).options(
            load_only(WarehousePlacement.part_id, WarehousePlacement.cabinet_id, WarehousePlacement.drawer_code),
            joinedload(WarehousePlacement.part),
        )
        if cabinet_id is not None:
            query = query.filter(WarehousePlacement.cabinet_id == cabinet_id,
                                 WarehousePlacement.drawer_code == drawer_code)
        occupants = {}
        for placement in query.all():
            if placement.part is not None:
                group = group_for_part(db, placement.part)
                occupants.setdefault((placement.cabinet_id, placement.drawer_code), {})[group.key] = group
        return occupants

    @staticmethod
    def _compatible_priority(group, occupants):
        if not occupants:
            return 2
        if group.kind == "mechanical":
            if len(occupants) > 2 or any(item.kind != "mechanical" for item in occupants.values()):
                return None
            if group.key in occupants:
                return 0
            return 1 if len(occupants) == 1 else None
        return 0 if set(occupants) == {group.key} else None

    @staticmethod
    def _suggest_group(db, group, drawer_type, part_id=None, quantity=1):
        if drawer_type not in {"S", "L"}:
            raise HTTPException(422, "Drawer type must be S or L")
        result = {"part_id": part_id, "drawer_type": drawer_type, "group": group.as_dict(),
                  "recommended": None, "candidates": [], "reason": "no_available_drawer"}
        if quantity <= 0:
            result["reason"] = "no_stock"
            return result
        occupants = WarehouseService._occupants(db)
        buckets = [[], [], []]
        for drawer in WarehouseService._drawers(drawer_type):
            groups = occupants.get((drawer["cabinet_id"], drawer["drawer_code"]), {})
            priority = WarehouseService._compatible_priority(group, groups)
            if priority is not None:
                buckets[priority].append({**drawer, "state": "empty" if priority == 2 else "compatible"})
        candidates = [drawer for bucket in buckets for drawer in bucket]
        result["candidates"] = candidates
        if candidates:
            result.update(recommended=candidates[0], reason=candidates[0]["state"])
        return result

    @staticmethod
    def suggest(db: Session, part_id: int, drawer_type: str = "S") -> dict:
        part = WarehouseService._part(db, part_id)
        group = group_for_part(db, part)
        placement = db.get(WarehousePlacement, part_id, options=[load_only(
            WarehousePlacement.part_id, WarehousePlacement.cabinet_id, WarehousePlacement.drawer_code)])
        inventory = db.get(Inventory, part_id)
        quantity = inventory.quantity_available or 0 if inventory else 0
        result = WarehouseService._suggest_group(db, group, drawer_type, part_id, 0 if placement else quantity)
        if placement:
            result.update(reason="already_placed", placement={"cabinet_id": placement.cabinet_id,
                          "drawer_code": placement.drawer_code})
        return result

    @staticmethod
    def suggest_component(db: Session, library_source: str, external_part_id: str,
                          quantity: int = 1, drawer_type: str = "S") -> dict:
        if library_source not in {"jlcparts", "altium", "kicad", "fasteners", "custom"} or quantity < 0:
            raise HTTPException(422, "Invalid component source or quantity")
        record = native_record(db, library_source, external_part_id)
        if not record:
            raise HTTPException(404, "Component not found in the local catalog")
        group = group_for_record(library_source, external_part_id, record)
        return WarehouseService._suggest_group(db, group, drawer_type, quantity=quantity)

    @staticmethod
    def _set_drawer_group(drawer, occupants):
        group = next(iter(occupants.values())) if len(occupants) == 1 else None
        drawer.group_key = group.key if group else None
        drawer.group_label = group.label if group else None

    @staticmethod
    def _begin_write(db):
        # SQLite has no SELECT FOR UPDATE. Acquire its write lock before reading
        # occupancy; MySQL locks the inventory part and the stable drawer row.
        if db.get_bind().dialect.name == "sqlite":
            connection = db.connection()
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif db.get_bind().dialect.name == "mysql":
            if db.in_transaction():
                raise HTTPException(409, "Placement requires a fresh transaction; retry the request")
            # Every occupancy read must see commits made while waiting for the
            # drawer lock. READ COMMITTED also avoids absent-placement gap locks.
            db.connection(execution_options={"isolation_level": "READ COMMITTED"})

    @staticmethod
    def _lock_drawer(db, cabinet_id, drawer_code):
        drawer = db.query(WarehouseDrawer).filter_by(
            cabinet_id=cabinet_id, drawer_code=drawer_code
        ).populate_existing().with_for_update().one_or_none()
        if drawer is None:
            raise HTTPException(409, "Warehouse configuration is not initialized")
        return drawer

    @staticmethod
    def _validate_photo(photo_data, photo_mime_type):
        if not photo_data:
            raise HTTPException(422, "A warehouse photo is required")
        if len(photo_data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Warehouse photo must be at most 10 MiB")
        valid = {
            "image/png": photo_data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": photo_data.startswith(b"\xff\xd8\xff"),
            "image/webp": photo_data[:4] == b"RIFF" and photo_data[8:12] == b"WEBP",
        }
        if not valid.get(photo_mime_type):
            raise HTTPException(422, "Upload a PNG, JPEG or WebP photo")

    @staticmethod
    def place(db: Session, part_id: int, cabinet_id: str, drawer_code: str,
              photo_data: bytes, photo_mime_type: str) -> dict:
        WarehouseService._validate_photo(photo_data, photo_mime_type)
        if not any(item["cabinet_id"] == cabinet_id and item["drawer_code"] == drawer_code
                   for item in WarehouseService._drawers()):
            raise HTTPException(422, "Unknown warehouse drawer")
        try:
            WarehouseService._begin_write(db)
            part = WarehouseService._part(db, part_id, lock=True)
            # The existing Part row lock serializes operations for this part.
            existing = db.query(WarehousePlacement).options(load_only(
                WarehousePlacement.part_id, WarehousePlacement.cabinet_id, WarehousePlacement.drawer_code
            )).filter_by(part_id=part_id).one_or_none()
            if existing:
                if (existing.cabinet_id, existing.drawer_code) != (cabinet_id, drawer_code):
                    raise HTTPException(409, "Remove the existing placement before moving this part")
                db.commit()
                return {"part_id": part_id, "cabinet_id": cabinet_id, "drawer_code": drawer_code,
                        "already_placed": True}
            inventory = db.query(Inventory).filter_by(part_id=part_id).populate_existing().with_for_update().one_or_none()
            if inventory is None or inventory.quantity_available <= 0:
                raise HTTPException(409, "Positive stock is required for physical placement")
            drawer = WarehouseService._lock_drawer(db, cabinet_id, drawer_code)
            group = group_for_part(db, part)
            groups = WarehouseService._occupants(db, cabinet_id, drawer_code).get((cabinet_id, drawer_code), {})
            if WarehouseService._compatible_priority(group, groups) is None:
                raise HTTPException(409, "Drawer is occupied by an incompatible group; request a new suggestion")
            db.add(WarehousePlacement(part_id=part_id, cabinet_id=cabinet_id, drawer_code=drawer_code,
                                      photo_data=photo_data, photo_mime_type=photo_mime_type))
            groups[group.key] = group
            WarehouseService._set_drawer_group(drawer, groups)
            part.storage_location = f"{cabinet_id} / {drawer_code}"
            db.commit()
            return {"part_id": part_id, "cabinet_id": cabinet_id, "drawer_code": drawer_code,
                    "already_placed": False}
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def remove(db: Session, part_id: int) -> dict:
        try:
            WarehouseService._begin_write(db)
            part = WarehouseService._part(db, part_id, lock=True)
            placement = db.query(WarehousePlacement).options(load_only(
                WarehousePlacement.part_id, WarehousePlacement.cabinet_id, WarehousePlacement.drawer_code
            )).filter_by(part_id=part_id).one_or_none()
            if placement is None:
                db.commit()
                return {"part_id": part_id, "removed": False}
            # Keep removal available for legacy placements outside current geometry.
            drawer = db.query(WarehouseDrawer).filter_by(cabinet_id=placement.cabinet_id,
                         drawer_code=placement.drawer_code).with_for_update().one_or_none()
            if part.storage_location == f"{placement.cabinet_id} / {placement.drawer_code}":
                part.storage_location = None
            cabinet_id, drawer_code = placement.cabinet_id, placement.drawer_code
            db.delete(placement)
            db.flush()
            if drawer:
                groups = WarehouseService._occupants(db, cabinet_id, drawer_code).get((cabinet_id, drawer_code), {})
                WarehouseService._set_drawer_group(drawer, groups)
            db.commit()
            return {"part_id": part_id, "removed": True}
        except Exception:
            db.rollback()
            raise

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
            load_only(WarehousePlacement.part_id, WarehousePlacement.cabinet_id, WarehousePlacement.drawer_code),
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
