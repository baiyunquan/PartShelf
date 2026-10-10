"""OCR API endpoints powered by PaddleOCR-VL-1.5 via llama.cpp."""

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services import paddleocr_client

router = APIRouter()


@router.post("/ocr")
async def process_ocr(image: UploadFile | None = File(None), file: UploadFile | None = File(None)):
    """Recognize text in uploaded image file."""
    upload = image or file
    if upload is None:
        raise HTTPException(422, "No image file provided in form-data ('image' or 'file')")
    data = await upload.read()
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Image file must be between 1 byte and 10 MiB")
    try:
        return paddleocr_client.recognize_image(data)
    except Exception as exc:
        raise HTTPException(503, f"OCR processing failed: {exc}") from exc
