"""Evaluate packaging samples using saved OCR only and isolated database snapshots."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--saved-scans", type=Path, required=True, help="Prior response array, with filenames, scan.label.image_sha256 and scan.ocr")
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True, help="Parent for a new isolated evaluation directory")
    args = parser.parse_args()
    run = args.work_dir.resolve()/str(uuid4()); run.mkdir(parents=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{run}/evaluation.sqlite"
    os.environ["PARTSHELF_TEST_MODE"] = "true"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.api.scan_api_routes import router
    from app.models import Project, ScanOCRResult
    from app.services import scan_import_service as scans, external_library_service as libraries, lcsc_dynamic_service as dynamic
    from app.services.scan_ocr_cache import cache_identity
    from app.user_identity import SESSION_USERNAME_KEY
    from db.database import Base, get_db
    for filename in ("jlcparts.db", "altium_library.db"):
        source = args.library_dir.resolve()/filename
        if source.exists():
            with sqlite3.connect(source.as_uri()+"?mode=ro", uri=True) as original, sqlite3.connect(run/filename) as target:
                original.backup(target)
        print(f"Catalog snapshot: {filename}", flush=True)
    libraries.JLCPARTS_DB_PATH = dynamic.JLCPARTS_DB_PATH = run/"jlcparts.db"
    libraries.ALTIUM_DB_PATH = run/"altium_library.db"
    scans.UPLOAD_DIR = run/"uploads"
    entries = json.loads(args.saved_scans.read_text())
    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.info[SESSION_USERNAME_KEY] = "Scan evaluation"
        db.add(Project(id=1, name="Isolated scan evaluation"))
        for entry in entries:
            original = entry["scan"]
            if original["label"].get("is_jlc_qr"):
                continue
            photo = (args.samples/entry["filename"]).read_bytes()
            key, digest = cache_identity(photo)
            if original["label"].get("image_sha256") != digest or not original.get("ocr"):
                raise ValueError(f"Missing or mismatched OCR evidence for {entry['filename']}")
            if db.get(ScanOCRResult, key) is None:
                db.add(ScanOCRResult(cache_key=key, image_sha256=digest, status="complete", result=original["ocr"]))
                db.flush()
        db.commit()
    def dependency():
        with factory() as db:
            db.info[SESSION_USERNAME_KEY] = "Scan evaluation"
            yield db
    calls = Counter()
    def forbidden_ocr(*args, **kwargs):
        calls["ocr"] += 1
        raise AssertionError("Saved sample evaluation must not call OCR")
    original_ai = scans.multi_turn_service.process
    def ai(lines):
        calls["ai"] += 1
        return original_ai(lines)
    scans.ocr_client.recognize_image = forbidden_ocr
    scans.multi_turn_service.process = ai
    app = FastAPI(); app.include_router(router, prefix="/api/scan"); app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    report = {"run_dir":str(run), "source_evidence":str(args.saved_scans.resolve()), "results":[], "summary":{}}
    for entry in entries:
        label = entry["scan"]["label"]
        qr = bool(label.get("is_jlc_qr"))
        payload = {key:value for key,value in label.items() if key not in {"is_jlc_qr","image_sha256"}}
        data = {"project_id":"1", "request_id":str(uuid4()), "qr_text":json.dumps(payload) if qr else ""}
        image = (args.samples/entry["filename"]).read_bytes()
        before = calls.copy(); started = time.monotonic()
        response = client.post("/api/scan/recognize", data=data, files={"image":(entry["filename"],image)})
        if response.status_code != 200:
            raise RuntimeError(f"{entry['filename']}: {response.status_code}: {response.text}")
        result = response.json()
        if qr and (calls["ocr"] != before["ocr"] or calls["ai"] != before["ai"]):
            raise AssertionError("JLC QR called OCR or AI")
        if calls["ocr"]:
            raise AssertionError("OCR was repeated")
        report["results"].append({"filename":entry["filename"], "path":"qr" if qr else "saved_ocr",
            "seconds":round(time.monotonic()-started,2), "ocr_calls":0, "scan":result})
        status_counts = Counter(row["scan"]["status"] for row in report["results"])
        report["summary"] = {**dict(status_counts), "samples":len(report["results"]), "ocr_calls":calls["ocr"],
            "ai_calls":calls["ai"], "qr_imported":sum(r["path"]=="qr" and r["scan"]["status"]=="imported" for r in report["results"]),
            "qr_quantity":sum((r["scan"]["quantity"] or 0) for r in report["results"] if r["path"]=="qr")}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(entry["filename"], result["status"], result["verification"]["reasons"], flush=True)
    print(json.dumps(report["summary"],ensure_ascii=False), flush=True)
    engine.dispose()


if __name__ == "__main__":
    main()
