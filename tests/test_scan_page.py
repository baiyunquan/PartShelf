from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web_routes import router


def test_scan_page_keeps_project_context_and_local_decoder_bindings_in_both_languages():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    for lang in ("zh", "en"):
        response = client.get(f"/scan-import?project_id=42&lang={lang}")
        assert response.status_code == 200
        assert 'data-project-id="42"' in response.text
        assert 'id="scan-project"' in response.text
        assert '/static/js/vendor/zxing-wasm/reader.js' in response.text
        assert 'id="scan-review-form"' in response.text
        assert 'id="page-translations"' in response.text
        assert 'href="/scan-import"' in response.text


def test_inventory_has_scan_page_entry():
    app = FastAPI()
    app.include_router(router)
    assert 'href="/scan-import"' in TestClient(app).get("/inventory").text
