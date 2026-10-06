from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from services.paddleocr_api.server import create_app
from services.paddleocr_api.engine import compatible_predictors


class Runtime:
    ready = True
    device = "cpu"

    def recognize(self, data):
        return {"image": {"width": 100, "height": 60, "rotation_degrees": 0},
                "lines": [{"text": "C965815", "confidence": 0.99,
                           "box": [[0, 0], [80, 0], [80, 20], [0, 20]]}], "elapsed_ms": 1}


def png():
    buffer = BytesIO()
    Image.new("RGB", (100, 60), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_ocr_http_contract_and_health_are_independent_of_partshelf():
    with TestClient(create_app(Runtime())) as client:
        assert client.get("/health").json()["ready"] is True
        result = client.post("/v1/ocr", files={"image": ("label.png", png(), "image/png")})
        assert result.status_code == 200
        assert result.json()["api_version"] == "1"
        assert result.json()["lines"][0]["text"] == "C965815"
        assert client.get("/openapi.json").status_code == 200


def test_invalid_image_is_rejected_before_inference():
    with TestClient(create_app(Runtime())) as client:
        response = client.post("/v1/ocr", files={"image": ("label.jpg", b"not an image", "image/jpeg")})
        assert response.status_code == 422


def test_paddle_compatibility_disables_only_the_failing_pass_and_restores_factory():
    from types import SimpleNamespace
    calls = []
    config = SimpleNamespace(delete_pass=lambda name: calls.append(name))
    original = lambda config: "predictor"
    inference = SimpleNamespace(create_predictor=original)
    with compatible_predictors(inference, True):
        assert inference.create_predictor(config) == "predictor"
    assert calls == ["self_attention_fuse_pass"]
    assert inference.create_predictor is original
