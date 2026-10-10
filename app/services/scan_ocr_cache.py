"""Persist one OCR attempt per image/model version, including failed attempts."""
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.models import ScanOCRResult
from app.services import paddleocr_client


LOGGER = logging.getLogger(__name__)


def recognize_once(db, image):
    digest = hashlib.sha256(image).hexdigest()
    version = os.getenv("PADDLEOCR_VL_CACHE_VERSION", "vl-1.5-exif-1536-jpeg92-v1")
    key = hashlib.sha256(f"{version}:{digest}".encode()).hexdigest()
    row = db.get(ScanOCRResult, key)
    owner = False
    if row is None:
        row = ScanOCRResult(cache_key=key, image_sha256=digest, status="processing")
        db.add(row)
        try:
            db.commit()
            owner = True
        except IntegrityError:
            db.rollback()
    else:
        db.commit()
    if owner:
        try:
            result = paddleocr_client.recognize_image(image)
        except Exception:
            LOGGER.exception("OCR failed for image %s", digest)
            result = {"api_version": "1", "status": "error", "error": "ocr_unavailable", "lines": [], "raw_text": ""}
        row = db.get(ScanOCRResult, key)
        row.result = result
        row.status = "complete"
        db.commit()
        return result
    # Network inference never holds a business database transaction open.
    deadline = time.monotonic() + min(60, float(os.getenv("PADDLEOCR_TIMEOUT_SECONDS", "30")) + 5)
    while True:
        row = db.get(ScanOCRResult, key, populate_existing=True)
        abandoned_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=max(180, float(os.getenv("PADDLEOCR_TIMEOUT_SECONDS", "30")) + 30))
        if row and row.status == "processing" and row.created_at < abandoned_before:
            interrupted = {"api_version": "1", "status": "error", "error": "ocr_interrupted", "lines": [], "raw_text": ""}
            db.query(ScanOCRResult).filter_by(cache_key=key, status="processing").filter(
                ScanOCRResult.created_at < abandoned_before).update(
                    {ScanOCRResult.status: "complete", ScanOCRResult.result: interrupted}, synchronize_session=False)
            db.commit()
            continue
        result = row.result if row and row.status == "complete" else None
        db.commit()
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            return {"api_version": "1", "status": "pending", "error": "ocr_processing", "lines": [], "raw_text": ""}
        time.sleep(0.1)
