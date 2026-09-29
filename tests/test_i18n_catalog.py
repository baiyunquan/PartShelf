import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "app" / "i18n" / "locales"


def flatten(source, prefix=""):
    entries = {}
    for key, value in source.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            entries.update(flatten(value, f"{path}."))
        else:
            entries[path] = value
    return entries


def test_catalog_keys_and_template_references():
    catalogs = {
        path.stem: flatten(json.loads(path.read_text(encoding="utf-8")))
        for path in LOCALES.glob("*.json")
    }
    assert set(catalogs) == {"zh", "en"}
    assert set(catalogs["zh"]) == set(catalogs["en"])
    references = set()
    for path in (ROOT / "templates").rglob("*.html"):
        references.update(re.findall(r"(?<![A-Za-z_])t\('([^']+)'", path.read_text(encoding="utf-8")))
    dynamic_prefixes = {"app.lang_"}
    missing = {key for key in references if key not in catalogs["zh"] and key not in dynamic_prefixes}
    assert not missing, f"Missing template translation keys: {sorted(missing)}"
    for prefix in dynamic_prefixes & references:
        assert all(f"{prefix}{lang}" in catalogs["zh"] for lang in catalogs)


def test_javascript_translation_references():
    catalog = flatten(json.loads((LOCALES / "zh.json").read_text(encoding="utf-8")))
    for page in ("inventory", "component_details", "warehouse"):
        script = ROOT / "static" / "js" / f"{page}.js"
        assert script.exists()
        section = "details" if page == "component_details" else page
        source = script.read_text(encoding="utf-8")
        refs = re.findall(r"\bI18N\.([a-z][a-z0-9_]*)\b", source)
        refs.extend(re.findall(r'\btranslation\("([a-z][a-z0-9_]*)"\)', source))
        assert refs
        assert not {f"{section}.{key}" for key in refs} - set(catalog)
