import json
from pathlib import Path
from typing import Any, Dict, Optional

CATEGORIES_DIR = Path(__file__).resolve().parent / "categories"
DEFAULT_LANGUAGE = "zh"
SUPPORTED_LANGUAGES = {"zh", "en"}


class CategoryI18n:
    def __init__(self):
        self._catalogs: Dict[str, Dict[str, Any]] = {}
        self._flat_maps: Dict[str, Dict[str, str]] = {}
        self._lower_maps: Dict[str, Dict[str, str]] = {}
        self.load()

    def load(self):
        for lang in SUPPORTED_LANGUAGES:
            path = CATEGORIES_DIR / f"{lang}.json"
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._catalogs[lang] = data
            else:
                self._catalogs[lang] = {"altium": {}, "primary": {}, "secondary": {}}

            # Pre-compute flat and lower maps for fast O(1) lookups
            flat = {}
            lower = {}
            cat_data = self._catalogs[lang]
            for section in ("altium", "primary", "secondary"):
                sec_dict = cat_data.get(section, {})
                for k, v in sec_dict.items():
                    flat[k] = v
                    lower[k.strip().casefold()] = v
            self._flat_maps[lang] = flat
            self._lower_maps[lang] = lower

    def _normalize_lang(self, lang: Optional[str]) -> str:
        if not lang or lang not in SUPPORTED_LANGUAGES:
            return DEFAULT_LANGUAGE
        return lang

    def translate_altium(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        if not name:
            return ""
        l = self._normalize_lang(lang)
        altium_map = self._catalogs.get(l, {}).get("altium", {})
        return altium_map.get(name) or self.translate(name, lang=l)

    def translate_primary(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        if not name:
            return ""
        l = self._normalize_lang(lang)
        pri_map = self._catalogs.get(l, {}).get("primary", {})
        return pri_map.get(name) or self.translate(name, lang=l)

    def translate_secondary(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        if not name:
            return ""
        l = self._normalize_lang(lang)
        sec_map = self._catalogs.get(l, {}).get("secondary", {})
        return sec_map.get(name) or self.translate(name, lang=l)

    def translate(self, name: str, lang: str = DEFAULT_LANGUAGE) -> str:
        if not name:
            return ""
        l = self._normalize_lang(lang)
        flat = self._flat_maps.get(l, {})
        if name in flat:
            return flat[name]

        # Case-insensitive / trimmed fallback
        lower_map = self._lower_maps.get(l, {})
        k = name.strip().casefold()
        if k in lower_map:
            return lower_map[k]

        return name

    def get_flat_translations(self, lang: str = DEFAULT_LANGUAGE) -> Dict[str, str]:
        l = self._normalize_lang(lang)
        return dict(self._flat_maps.get(l, {}))

    def get_all(self, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        l = self._normalize_lang(lang)
        return dict(self._catalogs.get(l, {}))


category_i18n = CategoryI18n()
