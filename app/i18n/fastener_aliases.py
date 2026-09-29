"""Compatibility wrappers for fastener labels and shared search aliases."""

from typing import Tuple

from app.services.search_alias_service import (
    curated_aliases_for_record,
    record_keys_for_query,
)

_DISPLAY_NAMES_ZH = {
    "IUTHeatInsert": "热熔螺母（热熔嵌件）",
    **{
        code: "平头螺丝（沉头螺钉）"
        for code in (
            "ASMEB18.6.1.2", "ASMEB18.6.1.3", "ASMEB18.6.3.1A",
            "ASMEB18.6.3.1B", "ISO10642", "ISO14581", "ISO2009",
            "ISO7046", "WN1413A", "WN1423",
        )
    },
}


def aliases_for_standard(standard_code: str) -> list[str]:
    """Return the configured Chinese names for one standard code."""
    return list(curated_aliases_for_record("fasteners", standard_code))


def localized_standard_name(standard_code: str, source_name: str, lang: str = "zh") -> str:
    """Use a curated Chinese label when available and otherwise retain source name."""
    if lang != "zh":
        return source_name or standard_code
    key = str(standard_code or "").strip().casefold()
    for code, name in _DISPLAY_NAMES_ZH.items():
        if code.casefold() == key:
            return name
    return source_name or standard_code


def expand_fastener_query(query: str) -> Tuple[str, ...]:
    """Map Chinese alias phrases within a query to their explicit standard codes."""
    return record_keys_for_query("fasteners", query)
