"""PaddleOCR-VL-1.5 llama.cpp translation layer adapter.

Translates image bytes into OpenAI-compatible multimodal requests to llama-server,
and maps the VLM output into the standardized PaddleOCR schema.
"""

import base64
from io import BytesIO
import logging
import os
import re
import time

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

LOGGER = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MAX_VLM_DIMENSION = 1536


class PaddleOCRVLAdapter:
    """Adapter bridging legacy PaddleOCR requests to llama.cpp PaddleOCR-VL-1.5."""

    def __init__(self, llama_url: str | None = None, timeout: float = 30.0):
        raw_url = llama_url or os.getenv("LLAMA_OCR_BASE_URL", "http://127.0.0.1:8083/v1")
        self.llama_url = raw_url.rstrip("/")
        self.timeout = float(os.getenv("LLAMA_OCR_TIMEOUT_SECONDS", str(timeout)))
        self._chat_url = f"{self.llama_url}/chat/completions" if self.llama_url.endswith("/v1") else f"{self.llama_url}/v1/chat/completions"
        self._health_url = f"{self.llama_url}/health" if not self.llama_url.endswith("/v1") else f"{self.llama_url[:-3]}/health"

    def is_ready(self) -> bool:
        """Check if the underlying llama.cpp multimodal server is healthy."""
        try:
            with httpx.Client(timeout=2.0, follow_redirects=True, trust_env=False) as client:
                resp = client.get(self._health_url)
                if resp.status_code == 200:
                    return True
                models_url = f"{self.llama_url}/models" if self.llama_url.endswith("/v1") else f"{self.llama_url}/v1/models"
                m_resp = client.get(models_url)
                return m_resp.status_code == 200
        except Exception:
            return False

    def preprocess_image(self, data: bytes) -> tuple[str, int, int]:
        """Validate, orient, scale, and base64-encode image for PaddleOCR-VL."""
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Image must be between 1 byte and 10 MiB")

        try:
            with Image.open(BytesIO(data)) as img:
                if img.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported format: Use JPEG, PNG or WebP")
                if img.width * img.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image must contain at most 24 million pixels")

                # Respect camera EXIF rotation
                normalized = ImageOps.exif_transpose(img).convert("RGB")
                orig_w, orig_h = normalized.size

                # Downscale proportionally if very large to optimize VLM token generation
                if max(orig_w, orig_h) > MAX_VLM_DIMENSION:
                    scale = MAX_VLM_DIMENSION / float(max(orig_w, orig_h))
                    target_w = max(1, int(orig_w * scale))
                    target_h = max(1, int(orig_h * scale))
                    export_img = normalized.resize((target_w, target_h), Image.Resampling.LANCZOS)
                else:
                    export_img = normalized

                buf = BytesIO()
                export_img.save(buf, format="JPEG", quality=92)
                b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
                data_url = f"data:image/jpeg;base64,{b64_str}"
                return data_url, orig_w, orig_h
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid packaging label image") from exc

    def recognize(self, data: bytes) -> dict:
        """Run OCR recognition via llama.cpp PaddleOCR-VL-1.5 and return legacy schema."""
        started = time.perf_counter()
        data_url, width, height = self.preprocess_image(data)

        payload = {
            "model": "paddleocr-vl",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "OCR:"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.0,
        }

        with httpx.Client(timeout=self.timeout, follow_redirects=True, trust_env=False) as client:
            resp = client.post(self._chat_url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"llama-server returned HTTP {resp.status_code}: {resp.text[:200]}")
            body = resp.json()

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("llama-server returned empty choices")

        content = choices[0].get("message", {}).get("content", "").strip()
        lines = []
        for line_raw in content.splitlines():
            line_text = line_raw.strip()
            if not line_text:
                continue
            lines.append({
                "text": line_text,
                "confidence": None,
                "box": None,
            })

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        finish = choices[0].get("finish_reason")
        repeated = any(content.splitlines().count(line["text"]) >= 4 for line in lines)
        repeated = repeated or bool(re.search(r"(.{12,160})(?:\s*\1){3,}", content))
        complete = finish == "stop" and bool(lines) and not repeated
        return {
            "engine": "paddleocr-vl-llama.cpp",
            "region": None,
            "confidence_source": "not_provided_by_model",
            "status": "complete" if complete else "incomplete",
            "finish_reason": finish,
            "error": None if complete else "ocr_empty" if not lines else "ocr_repeated" if repeated else "ocr_incomplete",
            "usage": body.get("usage"),
            "image": {
                "width": width,
                "height": height,
                "rotation_degrees": 0,
            },
            "lines": lines,
            "raw_text": content,
            "elapsed_ms": elapsed_ms,
        }
