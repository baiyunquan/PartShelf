"""Application configuration settings for PartShelf."""

import os
from pathlib import Path


class Settings:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./partshelf.db")

    # llama.cpp server configuration
    LLAMA_SERVER_BIN: str = os.getenv(
        "LLAMA_SERVER_BIN",
        r"E:\workspace\llama.cpp\build-cuda-icpx\bin\llama-server.exe",
    )
    LLAMA_EXTRACTOR_BASE_URL: str = os.getenv(
        "LLAMA_EXTRACTOR_BASE_URL",
        "http://127.0.0.1:8081/v1",
    )
    LLAMA_RERANKER_BASE_URL: str = os.getenv(
        "LLAMA_RERANKER_BASE_URL",
        "http://127.0.0.1:8082/v1",
    )
    LLAMA_API_KEY: str = os.getenv("LLAMA_API_KEY", "no-key")
    LLAMA_TIMEOUT_SECONDS: float = float(os.getenv("LLAMA_TIMEOUT_SECONDS", "30.0"))

    # Model file paths (defaults to unquantized BF16)
    LLAMA_EXTRACTOR_MODEL: str = os.getenv(
        "LLAMA_EXTRACTOR_MODEL",
        str(
            BASE_DIR.parent
            / "ElectronicQwen"
            / "deliverables"
            / "v1"
            / "ElectronicQwen-Extractor-v1-BF16.gguf"
        ),
    )
    LLAMA_RERANKER_MODEL: str = os.getenv(
        "LLAMA_RERANKER_MODEL",
        str(
            BASE_DIR.parent
            / "ElectronicQwen"
            / "deliverables"
            / "v1"
            / "ElectronicQwen-Reranker-v1-BF16.gguf"
        ),
    )

    LLAMA_EXTRACTOR_PORT: int = int(os.getenv("LLAMA_EXTRACTOR_PORT", "8081"))
    LLAMA_RERANKER_PORT: int = int(os.getenv("LLAMA_RERANKER_PORT", "8082"))
    LLAMA_STRICT_MODE: bool = os.getenv("LLAMA_STRICT_MODE", "true").lower() in ("1", "true")

    # PaddleOCR translation layer endpoint
    PADDLEOCR_API_URL: str = os.getenv("PADDLEOCR_API_URL", "http://127.0.0.1:8010")
    PADDLEOCR_TIMEOUT_SECONDS: float = float(os.getenv("PADDLEOCR_TIMEOUT_SECONDS", "30.0"))

    # PaddleOCR-VL-1.5 llama.cpp backend configuration (dedicated backend port 8083)
    LLAMA_OCR_BASE_URL: str = os.getenv(
        "LLAMA_OCR_BASE_URL",
        "http://127.0.0.1:8083/v1",
    )
    LLAMA_OCR_MODEL: str = os.getenv(
        "LLAMA_OCR_MODEL",
        str(
            BASE_DIR
            / "data"
            / "models"
            / "paddleocr_vl"
            / "PaddleOCR-VL-1.5.gguf"
        ),
    )
    LLAMA_OCR_MMPROJ: str = os.getenv(
        "LLAMA_OCR_MMPROJ",
        str(
            BASE_DIR
            / "data"
            / "models"
            / "paddleocr_vl"
            / "PaddleOCR-VL-1.5-mmproj.gguf"
        ),
    )
    LLAMA_OCR_PORT: int = int(os.getenv("LLAMA_OCR_PORT", "8083"))
    LLAMA_OCR_TIMEOUT_SECONDS: float = float(os.getenv("LLAMA_OCR_TIMEOUT_SECONDS", "30.0"))


settings = Settings()
