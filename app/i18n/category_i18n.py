import json
from pathlib import Path
from typing import Dict

from app.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

CATEGORIES_DIR = Path(__file__).resolve().parent / "categories"
SECTIONS = ("altium", "primary", "secondary")


class CategoryI18n:
    def __init__(self):
        self.load()

    def load(self):
        self._zh: Dict[str, Dict[str, str]] = json.loads(
            (CATEGORIES_DIR / "zh.json").read_text(encoding="utf-8")
        )
        self._normalized = {
            section: {key.strip().casefold(): value for key, value in self._zh[section].items()}
            for section in SECTIONS
        }

    def _translate(self, section: str, name: str, lang: str) -> str:
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        if not name or lang != DEFAULT_LANGUAGE:
            return name or ""
        return self._zh[section].get(name) or self._normalized[section].get(name.strip().casefold(), name)

    def translate_altium(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        return self._translate("altium", name, lang)

    def translate_primary(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        return self._translate("primary", name, lang)

    def translate_secondary(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        return self._translate("secondary", name, lang)

    def get_all(self, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Dict[str, str]]:
        if lang in SUPPORTED_LANGUAGES and lang != DEFAULT_LANGUAGE:
            return {section: {} for section in SECTIONS}
        return {section: dict(self._zh[section]) for section in SECTIONS}


category_i18n = CategoryI18n()
