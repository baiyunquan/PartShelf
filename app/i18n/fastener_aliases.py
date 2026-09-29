"""Chinese display names and search aliases for common mechanical standards."""

from typing import Dict, Tuple


_COUNTERSUNK_FLAT_CODES = (
    "ASMEB18.6.1.2",
    "ASMEB18.6.1.3",
    "ASMEB18.6.3.1A",
    "ASMEB18.6.3.1B",
    "ISO10642",
    "ISO14581",
    "ISO2009",
    "ISO7046",
    "WN1413A",
    "WN1423",
)

_ALIASES_BY_STANDARD: Dict[str, Tuple[str, ...]] = {
    "IUTHeatInsert": ("热熔螺母", "热熔铜螺母", "热熔嵌件", "热压嵌件"),
    **{
        code: ("平头螺丝", "沉头螺钉")
        for code in _COUNTERSUNK_FLAT_CODES
    },
}

_DISPLAY_NAMES_ZH = {
    "IUTHeatInsert": "热熔螺母（热熔嵌件）",
    **{
        code: "平头螺丝（沉头螺钉）"
        for code in _COUNTERSUNK_FLAT_CODES
    },
}

_ALIAS_TARGETS = {
    alias.casefold(): tuple(
        code for code, aliases in _ALIASES_BY_STANDARD.items() if alias in aliases
    )
    for aliases in _ALIASES_BY_STANDARD.values()
    for alias in aliases
}


def aliases_for_standard(standard_code: str) -> list[str]:
    """Return the configured Chinese names for one standard code."""
    key = str(standard_code or "").strip().casefold()
    for code, aliases in _ALIASES_BY_STANDARD.items():
        if code.casefold() == key:
            return list(aliases)
    return []


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
    normalized = " ".join(str(query or "").strip().casefold().split())
    exact = _ALIAS_TARGETS.get(normalized)
    if exact:
        return exact
    codes = []
    for alias in sorted(_ALIAS_TARGETS, key=len, reverse=True):
        if alias in normalized:
            codes.extend(_ALIAS_TARGETS[alias])
    return tuple(dict.fromkeys(codes))
