"""Download PaddleOCR-VL-1.5 GGUF models from ModelScope with resume support."""

import hashlib
import os
import sys
import time
import urllib.request
from pathlib import Path

DEST_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "paddleocr_vl"

FILES = [
    {
        "name": "chat_template.jinja",
        "url": "https://www.modelscope.cn/models/PaddlePaddle/PaddleOCR-VL-1.5-GGUF/resolve/master/chat_template.jinja",
        "size": 1831,
        "sha256": "1369e43952c7a84e834be95732d65111e96cbefe30aa32a4826eca344f5ef939",
    },
    {
        "name": "PaddleOCR-VL-1.5.gguf",
        "url": "https://www.modelscope.cn/models/PaddlePaddle/PaddleOCR-VL-1.5-GGUF/resolve/master/PaddleOCR-VL-1.5.gguf",
        "size": 935768992,
        "sha256": "299051d54faa065abc505cc39b8383ea338fd3020c775ea3e0ba514a7022328c",
    },
    {
        "name": "PaddleOCR-VL-1.5-mmproj.gguf",
        "url": "https://www.modelscope.cn/models/PaddlePaddle/PaddleOCR-VL-1.5-GGUF/resolve/master/PaddleOCR-VL-1.5-mmproj.gguf",
        "size": 881770496,
        "sha256": "e7f1a72400fba517046f90d964e2fa0f4dac7781ee3b1bc5d2022f5f8cecbd87",
    },
]


def check_sha256(filepath: Path, expected: str) -> bool:
    if not filepath.is_file():
        return False
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def download_file_with_resume(item: dict, target_dir: Path, max_retries: int = 10):
    target = target_dir / item["name"]
    temp = target.with_suffix(target.suffix + ".part")

    if target.is_file() and target.stat().st_size == item["size"]:
        print(f"[CHECK] Verifying existing {item['name']}...")
        if check_sha256(target, item["sha256"]):
            print(f"[OK] {item['name']} already exists and verified.")
            return
        print(f"[WARN] Hash mismatch for {item['name']}, re-downloading...")
        target.unlink(missing_ok=True)

    expected_size = item["size"]
    print(f"[DOWNLOAD] Starting {item['name']} ({expected_size / (1024*1024):.1f} MB)...")

    for attempt in range(1, max_retries + 1):
        existing_bytes = temp.stat().st_size if temp.is_file() else 0
        if existing_bytes >= expected_size:
            break

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "*/*",
        }
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"
            print(f"  -> Resuming {item['name']} from {existing_bytes / (1024*1024):.1f} MB (attempt {attempt}/{max_retries})...")

        req = urllib.request.Request(item["url"], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                mode = "ab" if existing_bytes > 0 else "wb"
                with open(temp, mode) as out:
                    downloaded = existing_bytes
                    start_time = time.time()
                    last_print = 0
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_print > 0.5 or downloaded >= expected_size:
                            last_print = now
                            pct = (downloaded / expected_size) * 100
                            speed = (downloaded - existing_bytes) / max(0.01, now - start_time) / (1024 * 1024)
                            print(f"  -> {pct:5.1f}% [{downloaded/(1024*1024):.1f}/{expected_size/(1024*1024):.1f} MB] ({speed:.1f} MB/s)   ", end="\r")
        except Exception as exc:
            print(f"\n[WARN] Attempt {attempt} interrupted: {exc}. Retrying...")
            time.sleep(1.0)

        if temp.is_file() and temp.stat().st_size >= expected_size:
            break

    print(f"\n[DOWNLOAD] Completed downloading {item['name']}.")
    print(f"[CHECK] Verifying SHA256 checksum for {item['name']}...")
    if not check_sha256(temp, item["sha256"]):
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum verification failed for {item['name']}")

    temp.replace(target)
    print(f"[OK] {item['name']} verified and moved into place.")


def main():
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("PaddleOCR-VL-1.5 GGUF Downloader")
    print(f"Target directory: {DEST_DIR}")
    print("=" * 60)
    for item in FILES:
        download_file_with_resume(item, DEST_DIR)
    print("=" * 60)
    print("All PaddleOCR-VL-1.5 model assets are ready.")
    print("=" * 60)


if __name__ == "__main__":
    main()
