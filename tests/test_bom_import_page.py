import json
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web_routes import router


client = TestClient(FastAPI())
client.app.include_router(router)


def test_bom_import_page_keeps_project_context_and_safe_return_target():
    response = client.get("/bom-import?project_id=42&lang=en")

    assert response.status_code == 200
    assert 'data-project-id="42"' in response.text
    assert 'data-return-url="/project_details?project_id=42"' in response.text
    assert 'id="bomPreviewTable"' in response.text
    assert 'id="bomSearchBindModal"' in response.text
    assert 'id="bomCustomPartModal"' in response.text
    assert 'type="application/json"' in response.text

    translations = re.search(
        r'<script id="page-translations" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert translations
    assert "btn_confirm_import" in json.loads(translations.group(1))


def test_bom_import_page_without_project_returns_to_projects():
    response = client.get("/bom-import")

    assert response.status_code == 200
    assert 'data-project-id=""' in response.text
    assert 'data-return-url="/projects"' in response.text


def test_project_pages_link_to_standalone_bom_page_without_the_old_main_modal():
    projects = client.get("/projects")
    project_details = client.get("/project_details?project_id=42")

    assert 'href="/bom-import"' in projects.text
    assert 'id="importBomButton"' in project_details.text
    assert 'bomImportModal' not in projects.text
    assert 'bomImportModal' not in project_details.text
