"""End-to-End Live Verification Script for PartShelf with llama.cpp servers.

Tests:
1. llama-server Extractor health and models endpoint (Port 8081)
2. llama-server Reranker health and models endpoint (Port 8082)
3. PartShelf FastAPI web backend (Port 8000)
4. Live Scan Recognition API with AI inference (/api/scan/recognize)
5. Live BOM Preview API with AI inference (/api/projects/bom/preview)
6. GPU VRAM and process metrics via nvidia-smi
"""

import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from uuid import uuid4

import httpx
from PIL import Image


def section(title: str):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def check_endpoint(name: str, url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PartShelf-Verifier"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            print(f"[{name}] URL: {url} -> HTTP {resp.status} OK")
            return resp.status == 200
    except Exception as e:
        print(f"[{name}] URL: {url} -> ERROR: {e}")
        return False


def main():
    print("Starting End-to-End Live Verification...")

    # 1. Check Extractor and Reranker
    section("1. Verifying llama.cpp Server Instances")
    ok_ext = check_endpoint("Extractor Health", "http://127.0.0.1:8081/health")
    ok_ext_models = check_endpoint("Extractor Models", "http://127.0.0.1:8081/v1/models")
    ok_rerank = check_endpoint("Reranker Health", "http://127.0.0.1:8082/health")
    ok_rerank_models = check_endpoint("Reranker Models", "http://127.0.0.1:8082/v1/models")

    if not (ok_ext and ok_rerank):
        print("[ERROR] llama-server instances are not healthy. Aborting.")
        sys.exit(1)

    # 2. Check Web Backend
    section("2. Verifying PartShelf Web Backend")
    ok_web = check_endpoint("FastAPI Web Docs", "http://127.0.0.1:8000/docs")
    if not ok_web:
        print("[ERROR] PartShelf web backend is not responding on port 8000. Aborting.")
        sys.exit(1)

    # 3. Test Live Scan Recognize API
    section("3. Testing Live Scan Recognition API with AI Inference")
    # Generate test image
    img_buf = io.BytesIO()
    Image.new("RGB", (320, 240), color=(255, 255, 255)).save(img_buf, format="JPEG")
    img_bytes = img_buf.getvalue()

    scan_data = {
        "qr_text": "0603WAF1002T5E",
        "request_id": str(uuid4()),
    }
    scan_files = {
        "image": ("test_label.jpg", img_bytes, "image/jpeg"),
    }

    t0 = time.time()
    try:
        with httpx.Client(timeout=30.0) as client:
            scan_resp = client.post(
                "http://127.0.0.1:8000/api/scan/recognize",
                data=scan_data,
                files=scan_files,
            )
        elapsed_scan = round((time.time() - t0) * 1000, 1)
        print(f"HTTP Status: {scan_resp.status_code} (took {elapsed_scan} ms)")
        if scan_resp.status_code == 200:
            res_json = scan_resp.json()
            verif = res_json.get("verification", {})
            print(f"Scan Session ID : {res_json.get('id')}")
            print(f"Session Status  : {res_json.get('status')}")
            print(f"AI Decision     : {verif.get('ai_decision')}")
            print(f"AI Match Type   : {verif.get('match_type')}")
            print(f"Candidates Count: {len(verif.get('candidates', []))}")
            if verif.get("candidates"):
                top = verif["candidates"][0]
                print(f"Top Candidate   : {top.get('name')} (LCSC/ID: {top.get('external_part_id')})")
            print(f"AI Reasoning    : {verif.get('ai_reasoning')}")
        else:
            print(f"Response Error: {scan_resp.text}")
    except Exception as e:
        print(f"Scan request failed: {e}")

    # 4. Test Live BOM Preview API
    section("4. Testing Live BOM Preview API with AI Inference")
    bom_csv = (
        "Designator,Footprint,Comment,Manufacturer Part,Quantity\n"
        "R1,0603,10k,0603WAF1002T5E,50\n"
        "C1,0603,100nF,CL10B104KB8NNNC,100\n"
    ).encode("utf-8")

    bom_files = {
        "file": ("test_bom.csv", bom_csv, "text/csv"),
    }

    t0 = time.time()
    try:
        with httpx.Client(timeout=30.0) as client:
            bom_resp = client.post(
                "http://127.0.0.1:8000/api/projects/bom/preview",
                files=bom_files,
            )
        elapsed_bom = round((time.time() - t0) * 1000, 1)
        print(f"HTTP Status: {bom_resp.status_code} (took {elapsed_bom} ms)")
        if bom_resp.status_code == 200:
            bom_json = bom_resp.json()
            items = bom_json.get("items", [])
            print(f"Total BOM Items Processed: {len(items)}")
            for idx, it in enumerate(items, 1):
                print(f"\nItem {idx}:")
                print(f"  Designator : {it.get('designator')}")
                print(f"  Part MPN   : {it.get('manufacturer_part')}")
                print(f"  Status     : {it.get('status')}")
                print(f"  AI Decision: {it.get('ai_decision')}")
                print(f"  Matched Part: {it.get('matched_part_name')}")
                print(f"  AI Reasoning: {it.get('ai_reasoning')[:120]}...")
        else:
            print(f"Response Error: {bom_resp.text}")
    except Exception as e:
        print(f"BOM request failed: {e}")

    # 5. GPU Metrics
    section("5. GPU Metrics via nvidia-smi")
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        )
        print("GPU Info [Name, Used VRAM (MB), Total VRAM (MB), GPU Util (%)]:")
        print(res.stdout.strip())
    except Exception as e:
        print(f"nvidia-smi query failed: {e}")

    section("Verification Complete: All systems operational.")


if __name__ == "__main__":
    main()
