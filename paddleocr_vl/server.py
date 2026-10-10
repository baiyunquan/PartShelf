"""FastAPI server for the PaddleOCR-VL-1.5 llama.cpp translation layer.

Exposes:
- GET  /health         -> Standard PaddleOCR health check
- POST /v1/ocr         -> Standard PaddleOCR multipart recognition endpoint
- GET  /v1/models      -> Model information
- POST /v1/chat/completions -> Pass-through to underlying llama.cpp server
"""

import argparse
from contextlib import asynccontextmanager
import os
import sys
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
import httpx
from starlette.concurrency import run_in_threadpool

from .adapter import MAX_IMAGE_BYTES, PaddleOCRVLAdapter


def create_app(adapter: PaddleOCRVLAdapter | None = None) -> FastAPI:
    configured_adapter = adapter

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if configured_adapter is None:
            llama_url = os.getenv("LLAMA_OCR_BASE_URL", "http://127.0.0.1:8083/v1")
            app.state.adapter = PaddleOCRVLAdapter(llama_url=llama_url)
        else:
            app.state.adapter = configured_adapter
        yield

    app = FastAPI(
        title="PartShelf PaddleOCR-VL-1.5 Translation Layer",
        version="1.5.0",
        lifespan=lifespan,
    )

    @app.get("/")
    def index():
        return {
            "service": "PaddleOCR-VL-1.5 llama.cpp Translation Layer",
            "version": "1.5.0",
            "status": "online",
        }

    @app.get("/health")
    async def health():
        ad = getattr(app.state, "adapter", None)
        if ad is None or not await run_in_threadpool(ad.is_ready):
            return JSONResponse(
                status_code=503,
                content={
                    "api_version": "1",
                    "ready": False,
                    "error": "Underlying llama-server for PaddleOCR-VL is not ready",
                },
            )
        return {
            "api_version": "1",
            "ready": True,
            "device": "cuda:0 (PaddleOCR-VL-1.5 via llama.cpp)",
            "engine": "PaddleOCR-VL-1.5",
        }

    @app.post("/v1/ocr")
    async def recognize(
        image: UploadFile | None = File(None),
        file: UploadFile | None = File(None),
    ):
        target = image or file
        if target is None:
            raise HTTPException(422, "No image provided. Pass multipart 'image' or 'file'.")

        data = await target.read(MAX_IMAGE_BYTES + 1)
        await target.close()

        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image file exceeds 10 MiB limit")

        ad = getattr(app.state, "adapter", None)
        if ad is None:
            raise HTTPException(503, "PaddleOCR adapter is uninitialized")

        try:
            result = await run_in_threadpool(ad.recognize, data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"OCR inference failed: {exc}") from exc

        return {
            "api_version": "1",
            "request_id": str(uuid4()),
            **result,
        }

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": "paddleocr-vl",
                    "object": "model",
                    "owned_by": "PartShelf",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def proxy_chat(request: Request):
        ad = getattr(app.state, "adapter", None)
        if ad is None:
            raise HTTPException(503, "Adapter uninitialized")
        body = await request.json()
        async with httpx.AsyncClient(timeout=ad.timeout) as client:
            resp = await client.post(ad._chat_url, json=body)
            return JSONResponse(status_code=resp.status_code, content=resp.json())

    return app


app = create_app()


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="PaddleOCR-VL-1.5 llama.cpp translation layer server.")
    parser.add_argument("--port", type=int, default=int(os.getenv("PADDLEOCR_PORT", "8010")), help="Port to listen on (default 8010)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default 127.0.0.1)")
    parser.add_argument("--llama-url", type=str, default=os.getenv("LLAMA_OCR_BASE_URL", "http://127.0.0.1:8083/v1"), help="Underlying llama-server URL")
    args = parser.parse_args()

    os.environ["LLAMA_OCR_BASE_URL"] = args.llama_url
    print(f"[PaddleOCR-VL Adapter] Starting on http://{args.host}:{args.port} pointing to {args.llama_url}...")
    uvicorn.run("paddleocr_vl.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()

