"""Archived PP-OCR API. Default inference is disabled; use paddleocr_vl.server."""

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from .engine import MAX_IMAGE_BYTES, load_image


def create_app(runtime=None):
    configured_runtime = runtime

    @asynccontextmanager
    async def lifespan(app):
        # Explicit runtime injection keeps historical contract tests usable without enabling PP-OCR.
        app.state.ocr = configured_runtime
        yield

    app = FastAPI(title="ElectronicQwen PaddleOCR API", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        engine = getattr(app.state, "ocr", None)
        if engine is None:
            raise HTTPException(503, "Legacy PP-OCR is disabled; use the llama.cpp PaddleOCR-VL adapter")
        if not engine or not engine.ready:
            raise HTTPException(503, "OCR model is not ready")
        return {"api_version": "1", "ready": True, "device": engine.device}

    @app.post("/v1/ocr")
    async def recognize(image: UploadFile = File(..., description="JPEG, PNG or WebP packaging photograph")):
        data = await image.read(MAX_IMAGE_BYTES + 1)
        await image.close()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image exceeds 10 MiB")
        try:
            await run_in_threadpool(load_image, data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        engine = getattr(app.state, "ocr", None)
        if not engine or not engine.ready:
            raise HTTPException(503, "OCR model is not ready")
        try:
            result = await run_in_threadpool(engine.recognize, data)
        except Exception as exc:
            raise HTTPException(503, "OCR inference failed; retry with a clear label image") from exc
        return {"api_version": "1", "request_id": str(uuid4()), **result}

    return app


app = create_app()
