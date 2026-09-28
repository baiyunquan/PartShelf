import json
from pathlib import Path
from typing import Any, Dict

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "zh"
SUPPORTED_LANGUAGES = {"zh", "en"}

class I18n:
    def __init__(self):
        self.translations: Dict[str, Dict[str, Any]] = {}
        self.load_translations()

    def load_translations(self):
        for lang in SUPPORTED_LANGUAGES:
            file_path = LOCALES_DIR / f"{lang}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations[lang] = json.load(f)
            else:
                self.translations[lang] = {}

    def get(self, key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE

        parts = key.split(".")
        val = self.translations.get(lang, {})
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                # Fallback to default language (zh)
                if lang != DEFAULT_LANGUAGE:
                    val = self.translations.get(DEFAULT_LANGUAGE, {})
                    for p in parts:
                        if isinstance(val, dict) and p in val:
                            val = val[p]
                        else:
                            val = key
                            break
                else:
                    val = key
                break

        if isinstance(val, str) and kwargs:
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return str(val) if val is not None else key

    def get_all(self, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        return self.translations.get(lang, self.translations.get(DEFAULT_LANGUAGE, {}))


i18n = I18n()
