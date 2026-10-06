"""HTTP-only client: PartShelf does not import Paddle or load OCR models."""

import json
import os
from urllib.parse import urlsplit

import httpx


def recognize_image(data: bytes) -> dict:
    base_url = os.getenv("PADDLEOCR_API_URL", "http://127.0.0.1:8010").rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Invalid PADDLEOCR_API_URL")
    timeout = float(os.getenv("PADDLEOCR_TIMEOUT_SECONDS", "60"))
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with client.stream("POST", base_url + "/v1/ocr", files={"image": ("label.jpg", data, "application/octet-stream")}) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise RuntimeError("OCR response exceeds 4 MiB")
                chunks.append(chunk)
    result = json.loads(b"".join(chunks))
    if not isinstance(result, dict) or result.get("api_version") != "1" or not isinstance(result.get("lines"), list):
        raise RuntimeError("Unsupported OCR response")
    if len(result["lines"]) > 2000:
        raise RuntimeError("Too many OCR text lines")
    return result
