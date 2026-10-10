"""HTTP client: PartShelf communicates with the standard PaddleOCR API endpoint.

Maintains the original PaddleOCR /v1/ocr interface contract intact.
Connects to the PaddleOCR-VL translation layer on port 8010 by default.
"""

import json
import os
from urllib.parse import urlsplit

import httpx


def recognize_image(data: bytes) -> dict:
    """Send image to the PaddleOCR API endpoint and parse standardized lines."""
    base_url = os.getenv("PADDLEOCR_API_URL", "http://127.0.0.1:8010").rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Invalid PADDLEOCR_API_URL")

    timeout = float(os.getenv("PADDLEOCR_TIMEOUT_SECONDS", "30.0"))
    ocr_url = f"{base_url}/ocr" if base_url.endswith("/v1") else f"{base_url}/v1/ocr"

    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with client.stream(
            "POST",
            ocr_url,
            files={"image": ("label.jpg", data, "application/octet-stream")},
        ) as response:
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
        raise RuntimeError("Unsupported OCR response format")
    if len(result["lines"]) > 2000:
        raise RuntimeError("Too many OCR text lines")
    return result
