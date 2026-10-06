"""Reusable PaddleOCR 2.x runtime and image validation."""

from io import BytesIO
from contextlib import contextmanager
import math
import os
import sys
import threading
import time

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000


@contextmanager
def compatible_predictors(inference, enabled):
    """Avoid Paddle 2.6.2's Linux CPU self-attention fusion SIGILL."""
    original = inference.create_predictor
    if enabled:
        def create(config):
            config.delete_pass("self_attention_fuse_pass")
            return original(config)
        inference.create_predictor = create
    try:
        yield
    finally:
        inference.create_predictor = original


def load_image(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image must be between 1 byte and 10 MiB")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Use a JPEG, PNG or WebP image")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image must contain at most 24 million pixels")
            return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid image") from exc


class OCRRuntime:
    def __init__(self):
        self.ready = False
        self.device = os.getenv("OCR_DEVICE", "cpu")
        self._lock = threading.Lock()
        self._engine = None

    def start(self):
        # Import this Cython extension before Paddle's bundled zlib symbols.
        import pyclipper  # noqa: F401
        import paddle
        from paddleocr import PaddleOCR

        options = {"use_angle_cls": True, "lang": "ch", "use_gpu": self.device.startswith("gpu"),
                   "show_log": False, "enable_mkldnn": False}
        for key in ("det_model_dir", "rec_model_dir", "cls_model_dir"):
            if os.getenv("OCR_" + key.upper()):
                options[key] = os.environ["OCR_" + key.upper()]
        affected = sys.platform.startswith("linux") and paddle.__version__ == "2.6.2" and not options["use_gpu"]
        with compatible_predictors(paddle.inference, affected):
            self._engine = PaddleOCR(**options)
        self.ready = True

    def recognize(self, data):
        import numpy as np

        started = time.perf_counter()
        image = load_image(data)
        # Pure numeric lines can defeat the 180-degree line classifier, so
        # preserve evidence from all document orientations for the consumer.
        best = None
        alternatives = []
        with self._lock:
            for angle in (0, 90, 180, 270):
                rotated = image.rotate(-angle, expand=True)
                array = np.asarray(rotated)[:, :, ::-1].copy()
                raw = self._engine.ocr(array, cls=True)
                lines = []
                for group in raw or []:
                    for box, (text, score) in group or []:
                        if not math.isfinite(float(score)):
                            continue
                        lines.append({"text": str(text), "confidence": float(score),
                                      "box": [[float(x), float(y)] for x, y in box]})
                quality = sum(len(line["text"]) * line["confidence"] ** 4 for line in lines)
                result = {"image": {"width": rotated.width, "height": rotated.height,
                                     "rotation_degrees": angle}, "lines": lines}
                alternatives.append(result)
                if best is None or quality > best[0]:
                    best = (quality, result)
        return {**best[1], "alternatives": alternatives,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}
