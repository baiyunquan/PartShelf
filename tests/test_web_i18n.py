import json
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web_routes import router
from app.i18n import i18n


client = TestClient(FastAPI())
client.app.include_router(router)


def test_language_switch_rejects_network_path():
    response = client.get(
        "/set_language", params={"lang": "en", "next": "//example.com/elsewhere"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_language_switch_keeps_inventory_search_and_removes_language_override():
    response = client.get("/inventory?search=R%26C&lang=en")
    match = re.search(r'href="([^"]*set_language\?lang=zh[^"]*)"', response.text)
    assert match
    switch_url = unescape(match.group(1))
    target = parse_qs(urlsplit(switch_url).query)["next"][0]
    assert target == "/inventory?search=R%26C"


def test_page_translations_are_safe_and_scoped():
    catalog = i18n.translations["en"]["inventory"]
    original = catalog["empty_hint"]
    catalog["empty_hint"] = "</script><script>alert(1)</script>"
    try:
        response = client.get("/inventory?lang=en")
        match = re.search(
            r'<script id="page-translations" type="application/json">(.*?)</script>',
            response.text, re.DOTALL,
        )
        assert match
        page = json.loads(match.group(1))
        assert page["empty_hint"] == catalog["empty_hint"]
        assert "home" not in page
        assert "</script><script>alert(1)" not in response.text
    finally:
        catalog["empty_hint"] = original
