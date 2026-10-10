from fastapi.testclient import TestClient
from services.paddleocr_api.server import create_app


def test_default_legacy_pp_ocr_service_cannot_load_models():
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 503
        assert "disabled" in client.get("/health").json()["detail"].lower()
