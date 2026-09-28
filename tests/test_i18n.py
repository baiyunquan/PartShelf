from app.i18n import I18n


def test_page_translations_fall_back_without_changing_catalogs():
    translator = I18n()
    english = translator.translations["en"]["inventory"]
    original = english.pop("empty_hint")
    try:
        page = translator.get_section("inventory", "en")
        assert page["empty_hint"] == translator.translations["zh"]["inventory"]["empty_hint"]
        assert page["btn_details"] == english["btn_details"]
        assert "empty_hint" not in english
    finally:
        english["empty_hint"] = original
