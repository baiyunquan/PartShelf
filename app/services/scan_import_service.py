"""Persistent scan review and atomic package/project import."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError

from app.models import Inventory, Part, Project, ProjectPart, ScanSession
from app.services import external_library_service as libraries, component_search_service
from app.services import paddleocr_client as ocr_client
from app.services.scan_verification import MAX_QUANTITY, parse_label, verify_label
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
    return {key: item.get(key) for key in ("lcsc", "mfr", "manufacturer", "package", "category", "subcategory",
            "description", "library_type", "source", "lcsc_url", "image_url_small")}


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
        lib_src = component.get("source") or component.get("library_source") or "jlcparts"
        ext_id = str(component.get("lcsc") or component.get("external_part_id") or component.get("id") or "")
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


def recognize(db, raw, image, project_id, request_id, lang="zh"):
    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        label = parse_label(raw)
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
            "qty": 1
        }

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
    fingerprint = hashlib.sha256(json.dumps(label, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
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
    # No business DB transaction remains open during network/model work.
    scan = _get(db, scan_id)
    label = scan.label
    db.commit()
    component = ocr = None
    failures = []
    try:
        ocr = ocr_client.recognize_image(image)
    except Exception:
        LOGGER.exception("OCR unavailable for scan %s", scan_id)
        failures.append("ocr_unavailable")

    ocr_lines = []
    if ocr and "lines" in ocr:
        ocr_lines = [l["text"] for l in ocr["lines"] if l.get("text")]
    if not label.get("is_jlc_qr") and label.get("raw") and str(label["raw"]) not in ocr_lines:
        ocr_lines.insert(0, str(label["raw"]))

    # 1. Fast-path check: standard JLC QR
    if label.get("is_jlc_qr") is not False and label.get("pc"):
        try:
            component = resolve_component(label["pc"], lang)
            if component is None:
                failures.append("catalog_unavailable")
        except Exception:
            LOGGER.exception("Catalog unavailable for scan %s", scan_id)
            failures.append("catalog_unavailable")
        verification = verify_label(label, component, ocr or {})
    else:
        # Non-JLC label / barcode / image only
        component = None
        verification = {
            "verified": False,
            "fields": {},
            "reasons": [],
        }

    # 2. If standard verification did NOT verify or label was non-JLC, invoke AI MultiTurnSearchService
    if (not verification.get("verified") or label.get("is_jlc_qr") is False) and ocr_lines:
        try:
            ai_res = multi_turn_service.process(ocr_lines)
            decision = ai_res.get("decision", "no_match")
            verification["ai_decision"] = decision
            verification["ai_reasoning"] = ai_res.get("reasoning", "")
            
            cands = []
            if ai_res.get("selected_component"):
                cands.append(ai_res["selected_component"])
            for c in ai_res.get("candidate_components", []):
                if not any(str(x.get("external_part_id") or x.get("lcsc")) == str(c.get("external_part_id") or c.get("lcsc")) for x in cands):
                    cands.append(c)
            verification["candidates"] = cands
            verification["match_type"] = f"ai_{decision}"

            if decision == "exact_match" and ai_res.get("selected_component"):
                sel = ai_res["selected_component"]
                raw_c = sel.get("raw_item") or sel
                c_id = sel.get("external_part_id") or raw_c.get("lcsc") or raw_c.get("id")
                if c_id and sel.get("source") == "jlcparts":
                    try:
                        resolved_c = resolve_component(c_id, lang)
                        component = resolved_c or raw_c
                    except Exception:
                        component = raw_c
                else:
                    component = raw_c
            elif decision == "ambiguous":
                if "ambiguous_candidates" not in verification["reasons"]:
                    verification["reasons"].append("ambiguous_candidates")
            elif decision == "no_match":
                if "ai_no_match" not in verification["reasons"]:
                    verification["reasons"].append("ai_no_match")

            # If candidates empty, populate from all_retrieved_candidates
            if not cands and ai_res.get("all_retrieved_candidates"):
                cands.extend(ai_res["all_retrieved_candidates"])
                verification["candidates"] = cands

            # Check for reused bag conflict
            candidate_pc = None
            if component:
                candidate_pc = str(component.get("lcsc") or "")
            elif cands:
                cand_first = cands[0]
                raw_cand = cand_first.get("raw_item") or cand_first
                candidate_pc = str(cand_first.get("external_part_id") or raw_cand.get("lcsc") or raw_cand.get("id") or "")
            if not candidate_pc and ocr_lines:
                for line in ocr_lines:
                    m_c = re.search(r"\bC(\d{4,})\b", line, re.IGNORECASE)
                    if m_c:
                        candidate_pc = m_c.group(1)
                        break

            if label.get("is_jlc_qr") is not False and label.get("pc") and candidate_pc:
                label_pc = str(label["pc"]).lstrip("Cc")
                candidate_pc_clean = candidate_pc.lstrip("Cc")
                if candidate_pc_clean and label_pc and candidate_pc_clean != label_pc:
                    verification["reused_bag_warning"] = True
                    if "reused_bag_conflict" not in verification["reasons"]:
                        verification["reasons"].append("reused_bag_conflict")
        except Exception as e:
            LOGGER.exception("MultiTurnSearchService error for scan %s: %s", scan_id, e)
            verification["ai_error"] = str(e)

    _begin_write(db)
    scan = _get(db, scan_id, lock=True)
    if scan.status == "imported":
        db.commit()
        return scan
    scan.ocr = ocr
    scan.component = _component_snapshot(component)
    scan.status = "needs_review"
    scan.verification = verification
    if failures:
        scan.verification = {**scan.verification, "verified": False,
                             "reasons": [*failures, *scan.verification["reasons"]]}
    db.commit()
    if scan.verification["verified"]:
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


def confirm(db, scan_id, code, quantity, note="", new_package=False, lang="zh"):
    scan = _get(db, scan_id)
    if scan.status == "imported":
        return scan
    if scan.status == "processing":
        raise HTTPException(409, "Scan is still processing")
    if scan.status == "duplicate" and not new_package:
        raise HTTPException(409, "Confirm this is a different physical package")
    _project(db, scan.project_id, importing=True, expected_token=scan.project_token)
    db.commit()
    component = None
    try:
        if str(code).upper().startswith("C") and str(code)[1:].isdigit():
            component = resolve_component(code, lang)
        elif str(code).isdigit():
            component = resolve_component(f"C{code}", lang)

        # If not resolved via standard C-code, check candidates or scan.component
        if component is None:
            cands = (scan.verification or {}).get("candidates", [])
            for c in cands:
                c_id = str(c.get("external_part_id") or c.get("lcsc") or "")
                c_name = str(c.get("mfr_part_number") or c.get("name") or "")
                if code in (c_id, f"C{c_id}", c_name):
                    component = c.get("raw_item") or c
                    break
        if component is None and scan.component:
            comp_id = str(scan.component.get("lcsc") or scan.component.get("external_part_id") or "")
            comp_mfr = str(scan.component.get("mfr") or "")
            if code in (comp_id, f"C{comp_id}", comp_mfr):
                component = scan.component
    except Exception as exc:
        raise HTTPException(503, "Catalog lookup or cache unavailable") from exc
    if component is None:
        raise HTTPException(404, "Component not found in the catalog")
    return import_package(db, scan_id, component, quantity, note, new_package)


def public_scan(scan):
    utc = lambda value: value.replace(tzinfo=timezone.utc).isoformat() if value else None
    return {"id": scan.id, "request_id": scan.request_id, "status": scan.status,
            "created_at": utc(scan.created_at), "imported_at": utc(scan.imported_at), "username": scan.username,
            "imported_by": scan.imported_by, "project_id": scan.project_id, "project_name": scan.project_name,
            "part_id": scan.part_id, "quantity": scan.quantity, "label": scan.label, "component": scan.component,
            "ocr": scan.ocr, "verification": scan.verification, "note": scan.note,
            "image_url": f"/api/scan/{scan.id}/image"}
