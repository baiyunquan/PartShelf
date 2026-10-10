"""Persistent scan review and atomic package/project import."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import logging
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError

from app.models import Inventory, Part, Project, ProjectPart, ScanSession, WarehousePlacement
from app.services import external_library_service as libraries, component_search_service
from app.services import paddleocr_client as ocr_client
from app.services.scan_verification import MAX_QUANTITY, parse_label
from app.services.scan_evidence import verify_text, quantities, connector_observations
from app.services.scan_ocr_cache import recognize_once
from app.services.multi_turn_search_service import multi_turn_service
from app.user_identity import SESSION_USERNAME_KEY, require_project_history_username


UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "scan_uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


def resolve_component(code, lang="zh"):
    item = libraries.get_jlcparts_component(int(str(code).lstrip("Cc")), lang)
    if item is not None and component_search_service.get_local_lcsc_component(code) is None:
        raise RuntimeError("Component could not be persisted in the catalog cache")
    return item


def _component_snapshot(item):
    if item is None:
        return None
    raw = item.get("raw_item") or {}
    merged = {**raw, **{key: value for key, value in item.items() if key != "raw_item"}}
    source = merged.get("library_source") or merged.get("source")
    if source == "lcsc_dynamic":
        source = "jlcparts"
    if source not in {"jlcparts", "altium", "kicad", "custom"}:
        source = "jlcparts" if merged.get("lcsc") else "altium" if merged.get("lib_reference") else None
    identity = merged.get("external_part_id") or (merged.get("lcsc") if source == "jlcparts" else merged.get("id"))
    if source == "jlcparts" and identity is not None:
        identity = str(identity).lstrip("Cc")
    snapshot = {key: merged.get(key) for key in ("id", "lcsc", "lcsc_part", "mfr", "mfr_part_number", "lib_reference", "name",
                "manufacturer", "package", "category", "subcategory", "description", "library_type", "lcsc_url",
                "image_url_small", "capacitance", "resistance", "inductance", "attributes", "attributes_dict",
                "parameters_json", "parameters", "voltage_rating", "power_rating", "tolerance", "retrieval_truncated")}
    snapshot.update(library_source=source, source=source, external_part_id=str(identity) if identity is not None else None)
    return snapshot


def _project(db, project_id, *, importing=False, expected_token=None):
    if project_id is None:
        return None
    query = db.query(Project).filter_by(id=project_id)
    if importing:
        query = query.populate_existing().with_for_update()
    project = query.one_or_none()
    if project is None:
        raise HTTPException(409 if importing else 400, "Selected project no longer exists")
    if importing and (not expected_token or project.identity_token != expected_token):
        raise HTTPException(409, "Original project was deleted or replaced; rescan for the intended project")
    if project.system_key:
        raise HTTPException(400, "System projects are read-only")
    require_project_history_username(db)
    return project


def _get(db, scan_id, lock=False):
    query = db.query(ScanSession).filter_by(id=scan_id)
    if lock:
        query = query.populate_existing().with_for_update()
    scan = query.one_or_none()
    if scan is None:
        raise HTTPException(404, "Scan record not found")
    return scan


def _begin_write(db):
    db.rollback()
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def import_package(db, scan_id, component, quantity, note="", new_package=False):
    if not 1 <= quantity <= MAX_QUANTITY:
        raise HTTPException(422, "Quantity must be a positive integer")
    _begin_write(db)
    try:
        scan = _get(db, scan_id, lock=True)
        if scan.status == "imported":
            db.commit()
            return scan
        if scan.status == "processing":
            raise HTTPException(409, "Scan is still processing; wait for verification")
        previous = db.query(ScanSession).filter_by(claim_key=scan.fingerprint).first()
        if previous and previous.id != scan.id and not new_package:
            scan.status = "duplicate"
            scan.verification = {**(scan.verification or {}), "duplicate_part_id": previous.part_id,
                                 "reasons": ["duplicate"]}
            db.commit()
            return scan
        project = _project(db, scan.project_id, importing=True, expected_token=scan.project_token)
        scan.claim_key = None if previous and previous.id != scan.id else scan.fingerprint
        db.flush()  # acquire the unique claim before adding stock
        component = _component_snapshot(component)
        lib_src, ext_id = component["library_source"], component["external_part_id"]
        if not lib_src or not ext_id:
            raise HTTPException(422, "Component is missing its catalog identity")
        part = Part(library_source=lib_src, external_part_id=ext_id,
                    storage_location="Default Storage", note=note)
        db.add(part)
        db.flush()
        db.add(Inventory(part_id=part.id, quantity_available=quantity))
        if project:
            db.add(ProjectPart(project_id=project.id, part_id=part.id, quantity_needed=quantity,
                               project=project, part=part))
        scan.status = "imported"
        scan.part_id = part.id
        scan.quantity = quantity
        scan.note = note
        scan.component = _component_snapshot(component)
        scan.imported_by = db.info.get(SESSION_USERNAME_KEY)
        scan.imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return scan
    except IntegrityError:
        db.rollback()
        scan = _get(db, scan_id)
        previous = db.query(ScanSession).filter_by(claim_key=scan.fingerprint).first()
        if previous is None or previous.id == scan.id:
            raise
        scan.status = "duplicate"
        scan.verification = {**(scan.verification or {}), "duplicate_part_id": previous.part_id, "reasons": ["duplicate"]}
        db.commit()
        return scan
    except Exception:
        db.rollback()
        raise


def recognize(db, raw, image, project_id, request_id, lang="zh", qr_texts=None):
    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        label = parse_label(raw, allow_incomplete=True)
        label["is_jlc_qr"] = True
    except (ValueError, TypeError) as exc:
        if not image or len(image) == 0:
            raise HTTPException(422, str(exc)) from exc
        clean_raw = str(raw or "").strip()
        label = {
            "is_jlc_qr": False,
            "raw": clean_raw,
            "pc": None,
            "pm": clean_raw if clean_raw else "Scanned Part",
            "qty": None
        }

    if qr_texts:
        parsed = []
        for text in qr_texts:
            try:
                candidate = parse_label(text, allow_incomplete=True)
                if candidate not in parsed:
                    parsed.append(candidate)
            except (ValueError, TypeError):
                continue
        if len(parsed) > 1:
            label = {"is_jlc_qr": True, "multiple_labels": parsed, "pc": None, "pm": "", "qty": None}
        elif len(parsed) == 1:
            label = {**parsed[0], "is_jlc_qr": True}

    existing = db.query(ScanSession).filter_by(request_id=request_id).first()
    if existing:
        return existing
    project = _project(db, project_id)
    if not image or len(image) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image must be between 1 byte and 10 MiB")
    try:
        with Image.open(BytesIO(image)) as photo:
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(photo.format)
            if extension is None or photo.width * photo.height > 24_000_000:
                raise ValueError("Use a JPEG, PNG or WebP image with at most 24 million pixels")
            photo.verify()
    except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Invalid label image") from exc
    scan_id = str(uuid4())
    if label.get("is_jlc_qr"):
        fingerprint = hashlib.sha256(json.dumps(label, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    else:
        label["image_sha256"] = hashlib.sha256(image).hexdigest()
        fingerprint = label["image_sha256"]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = scan_id + extension
    path = UPLOAD_DIR / filename
    path.write_bytes(image)
    scan = ScanSession(id=scan_id, request_id=request_id, fingerprint=fingerprint, status="processing",
                       project_id=project_id, project_token=project.identity_token if project else None,
                       project_name=project.name if project else None,
                       username=db.info.get(SESSION_USERNAME_KEY), image_filename=filename, label=label,
                       verification={"verified": False, "fields": {}, "reasons": [],
                                     "processing_started_at": datetime.now(timezone.utc).isoformat()})
    db.add(scan)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        path.unlink(missing_ok=True)
        existing = db.query(ScanSession).filter_by(request_id=request_id).first()
        if existing is None:
            raise
        return existing
    return verify_scan(db, scan_id, image, lang)


def verify_scan(db, scan_id, image, lang="zh"):
    # Release the business transaction before catalog and model requests.
    scan = _get(db, scan_id)
    label, ocr = dict(scan.label), scan.ocr
    db.commit()
    component = None
    verification = {"verified": False, "fields": {}, "reasons": []}
    if label.get("is_jlc_qr"):
        verification["match_type"] = "jlc_qr"
        if label.get("multiple_labels"):
            verification["reasons"].append("multiple_labels")
        else:
            try:
                component = resolve_component(label["pc"], lang)
            except Exception:
                LOGGER.exception("Catalog unavailable for scan %s", scan_id)
            if component is None:
                verification["reasons"].append("catalog_unavailable")
            if not label.get("qty"):
                verification["reasons"].append("quantity")
            verification["verified"] = not verification["reasons"]
        # A JLC QR is authoritative and never falls through to OCR or AI.
        ocr = None
    else:
        if ocr is None or ocr.get("status") == "pending":
            ocr = recognize_once(db, image)
        status = ocr.get("status", "complete")
        if status != "complete":
            verification["reasons"].append(ocr.get("error") or "ocr_incomplete")
        else:
            lines = [line["text"] for line in ocr.get("lines", []) if line.get("text")]
            verification["observations"] = connector_observations(lines)
            counts = quantities(lines)
            valid_quantity = len(counts) == 1 and 1 <= next(iter(counts)) <= MAX_QUANTITY
            label["qty"] = next(iter(counts)) if valid_quantity else None
            verification["fields"]["quantity"] = {"matched": valid_quantity, "expected": label["qty"],
                "text": ", ".join(map(str, sorted(counts))), "evidence": [
                    {"line_index": i, "text": line} for i,line in enumerate(lines) if quantities([line])]}
            if not lines:
                verification["reasons"].append("ocr_empty")
            else:
                try:
                    result = multi_turn_service.process(lines)
                    decision = result.get("decision", "no_match")
                    verification.update(ai_decision=decision, ai_reasoning=result.get("reasoning", ""),
                                        match_type=f"ai_{decision}")
                    verification["stages"] = result.get("stages", {})
                    verification["field_evidence"] = result.get("field_evidence", {})
                    candidates = []
                    for candidate in [result.get("selected_component"), *result.get("candidate_components", []),
                                      *result.get("all_retrieved_candidates", [])]:
                        if candidate:
                            snapshot = _component_snapshot(candidate)
                            if not any((c["library_source"], c["external_part_id"]) ==
                                       (snapshot["library_source"], snapshot["external_part_id"]) for c in candidates):
                                candidates.append(snapshot)
                    verification["candidates"] = candidates
                    if decision == "exact_match" and result.get("selected_component"):
                        component = _component_snapshot(result["selected_component"])
                        if component["library_source"] == "jlcparts":
                            # Require the canonical local/remote cache record before writing a reference.
                            component = _component_snapshot(resolve_component(component["external_part_id"], lang))
                        if component:
                            evidence = verify_text(component, lines)
                            verification.update(evidence)
                            label["qty"] = evidence["quantity"]
                            compatible = [candidate for candidate in candidates if verify_text(candidate, lines)["verified"]]
                            if len(compatible) > 1:
                                verification["verified"] = False
                                verification["reasons"].append("ambiguous_candidates")
                            if any(candidate.get("retrieval_truncated") for candidate in candidates):
                                verification["verified"] = False
                                if "ambiguous_candidates" not in verification["reasons"]:
                                    verification["reasons"].append("ambiguous_candidates")
                        else:
                            verification["reasons"].append("catalog_unavailable")
                    elif decision == "ambiguous":
                        verification["reasons"].append("ambiguous_candidates")
                    else:
                        verification["reasons"].append("ai_no_match")
                    if any(stage.get("status") == "heuristic" for stage in result.get("stages", {}).values()):
                        verification["verified"] = False
                        verification["reasons"].append("ai_unavailable")
                except Exception as exc:
                    LOGGER.exception("AI search failed for scan %s", scan_id)
                    verification.update(ai_error=str(exc), verified=False)
                    verification["stage_errors"] = [exc.details] if hasattr(exc, "details") else [{"stage":"matching","code":"internal_error","attempts":1}]
                    verification["reasons"].append("ai_unavailable")
                # A reused bag can expose old and new quantities even when neither model is in the catalog.
                counts = quantities(lines)
                if len(counts) > 1 or any(count <= 0 or count > MAX_QUANTITY for count in counts):
                    verification["verified"] = False
                    if "quantity" not in verification["reasons"]:
                        verification["reasons"].append("quantity")
                    verification["fields"]["quantity"] = {"matched": False, "expected": None,
                                                           "text": ", ".join(map(str, sorted(counts)))}

    _begin_write(db)
    scan = _get(db, scan_id, lock=True)
    if scan.status == "imported":
        db.commit()
        return scan
    scan.ocr = ocr
    scan.label = label
    scan.component = _component_snapshot(component)
    scan.status = "needs_review"
    scan.verification = verification
    db.commit()
    if verification["verified"]:
        try:
            return import_package(db, scan_id, component, label["qty"])
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            _begin_write(db)
            scan = _get(db, scan_id, lock=True)
            if scan.status in {"imported", "processing"}:
                db.commit()
                return scan
            scan.verification = {**scan.verification, "verified": False, "reasons": ["project_unavailable"]}
            db.commit()
    return scan


def retry_scan(db, scan_id, lang="zh"):
    _begin_write(db)
    scan = _get(db, scan_id, lock=True)
    if scan.status == "imported":
        db.commit()
        return scan
    if scan.status == "processing":
        stamp = (scan.verification or {}).get("processing_started_at")
        started = datetime.fromisoformat(stamp).replace(tzinfo=None) if stamp else scan.created_at
        age = (datetime.now(timezone.utc).replace(tzinfo=None) - started).total_seconds()
        if age < 180:
            raise HTTPException(409, "Scan is still processing; retry later")
    _project(db, scan.project_id, importing=True, expected_token=scan.project_token)
    path = UPLOAD_DIR / scan.image_filename
    if not path.is_file():
        raise HTTPException(404, "Scan image not found")
    scan.status = "processing"
    scan.verification = {**scan.verification, "processing_started_at": datetime.now(timezone.utc).isoformat()}
    db.commit()
    return verify_scan(db, scan_id, path.read_bytes(), lang)


def confirm(db, scan_id, code, quantity, note="", new_package=False, lang="zh",
            library_source=None, external_part_id=None):
    scan = _get(db, scan_id)
    if scan.status == "imported":
        return scan
    if scan.status == "processing":
        raise HTTPException(409, "Scan is still processing")
    if scan.status == "duplicate" and not new_package:
        raise HTTPException(409, "Confirm this is a different physical package")
    _project(db, scan.project_id, importing=True, expected_token=scan.project_token)
    saved = [*(scan.verification or {}).get("candidates", []), scan.component]
    db.commit()
    component = None
    try:
        if library_source:
            if library_source == "jlcparts":
                component = resolve_component(external_part_id, lang)
            elif library_source == "altium":
                component = libraries.get_altium_component(int(external_part_id), lang)
            elif library_source == "kicad":
                component = libraries.get_kicad_symbol(int(external_part_id))
            else:
                raise HTTPException(422, "Unsupported catalog")
            if component:
                component = {**component, "library_source": library_source, "external_part_id": str(external_part_id)}
        else:
            # Legacy C-code confirmation remains compatible. Bare IDs require an unambiguous saved candidate.
            if re.fullmatch(r"C\d{3,10}", str(code or ""), re.I):
                component = resolve_component(code, lang)
            else:
                matched = []
                for candidate in saved:
                    if not candidate:
                        continue
                    snapshot = _component_snapshot(candidate)
                    if str(code) in {snapshot.get("external_part_id"), snapshot.get("mfr"),
                                     snapshot.get("mfr_part_number"), snapshot.get("name")}:
                        if snapshot not in matched:
                            matched.append(snapshot)
                if len(matched) > 1:
                    raise HTTPException(422, "Select a catalog and component identifier")
                if matched:
                    component = matched[0]
                elif str(code or "").isdigit():
                    component = resolve_component(f"C{code}", lang)
            if component is None:
                for candidate in saved:
                    snapshot = _component_snapshot(candidate)
                    if snapshot and snapshot["library_source"] == "jlcparts" and str(code).upper() == f"C{snapshot['external_part_id']}":
                        component = snapshot
                        break
    except HTTPException:
        raise
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid catalog identifier") from exc
    except Exception as exc:
        raise HTTPException(503, "Catalog lookup or cache unavailable") from exc
    if component is None:
        raise HTTPException(404, "Component not found in the catalog")
    return import_package(db, scan_id, component, quantity, note, new_package)


def public_scan(scan, db=None):
    utc = lambda value: value.replace(tzinfo=timezone.utc).isoformat() if value else None
    verification = dict(scan.verification or {})
    if "candidates" in verification:
        verification["candidates"] = [_component_snapshot(candidate) for candidate in verification["candidates"] if candidate]
    placement = None
    if db is not None and scan.part_id:
        p = db.get(WarehousePlacement, scan.part_id)
        if p is not None:
            placement = {"cabinet_id": p.cabinet_id, "drawer_code": p.drawer_code}
    return {"id": scan.id, "request_id": scan.request_id, "status": scan.status,
            "created_at": utc(scan.created_at), "imported_at": utc(scan.imported_at), "username": scan.username,
            "imported_by": scan.imported_by, "project_id": scan.project_id, "project_name": scan.project_name,
            "part_id": scan.part_id, "quantity": scan.quantity, "label": scan.label, "component": _component_snapshot(scan.component),
            "ocr": scan.ocr, "verification": verification, "note": scan.note,
            "image_url": f"/api/scan/{scan.id}/image",
            "placement": placement}
