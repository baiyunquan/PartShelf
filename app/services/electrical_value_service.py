"""Parse explicit electrical values without interpreting component model codes."""

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Dict, Iterable, Optional, Tuple


PARSER_VERSION = "2"
_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_RANGE_SEPARATOR = r"(?:[-–—~]|[Tt][Oo]|至|到)"
_VALUE = re.compile(
    rf"(?<![A-Za-z0-9_.])(?P<number>{_NUMBER})\s*"
    r"(?P<prefix>[pPnNuUmkKMGT]?)\s*"
    r"(?P<unit>[FfHhRrΩΩ]|[Oo][Hh][Mm][Ss]?|欧姆)(?![A-Za-z0-9_])"
)
_RESISTOR = re.compile(r"(?<![A-Za-z0-9_.])(\d+)([RrKkM])(\d+)(?![A-Za-z0-9_])")
_SCALES = {
    "p": -12, "n": -9, "u": -6, "m": -3, "": 0,
    "k": 3, "M": 6, "G": 9, "T": 12,
}
_PARAMETER_KEYS = {
    "capacitance": "capacitance", "电容": "capacitance", "电容量": "capacitance",
    "resistance": "resistance", "dc resistance": "resistance", "dcr": "resistance",
    "电阻": "resistance", "阻值": "resistance",
    "inductance": "inductance", "电感": "inductance", "电感量": "inductance",
}


@dataclass(frozen=True)
class Measurement:
    kind: str
    value: str
    text: str
    start: int
    end: int


def normalize_value_text(text: Any) -> str:
    """Preserve prefix case while normalizing Unicode and micro symbols."""
    return unicodedata.normalize("NFKC", str(text or "")).replace("μ", "u").replace("µ", "u")


def _canonical(number: str, prefix: str) -> Optional[str]:
    if len(number) > 128:
        return None
    exponent = re.search(r"[eE]([+-]?\d+)$", number)
    if exponent and (len(exponent.group(1)) > 4 or abs(int(exponent.group(1))) > 100):
        return None
    try:
        with localcontext() as context:
            context.prec = 160
            result = Decimal(number).scaleb(_SCALES[prefix])
            return "0" if result == 0 else format(result.normalize(), "f")
    except (InvalidOperation, KeyError):
        return None


def _is_ambiguous_context(text: str, start: int, end: int) -> bool:
    before, after = text[:start], text[end:]
    return bool(
        re.search(r"(?:^|\s)[−-]\s*$", before)
        or re.search(rf"{_NUMBER}\s*(?:[A-Za-zΩΩ]*)\s*{_RANGE_SEPARATOR}\s*$", before)
        or re.match(rf"\s*{_RANGE_SEPARATOR}\s*\d", after)
        or re.search(r"[A-Za-z][A-Za-z0-9_.]*[-_]$", before)
        or re.match(r"^[-_][A-Za-z]", after)
    )


def parse_measurements(text: Any) -> Tuple[Measurement, ...]:
    """Extract standalone C/R/L quantities, including complete resistor shorthand."""
    value = normalize_value_text(text)
    result = []
    for match in _VALUE.finditer(value):
        if _is_ambiguous_context(value, match.start(), match.end()):
            continue
        unit = match.group("unit").casefold()
        kind = "capacitance" if unit == "f" else "inductance" if unit == "h" else "resistance"
        prefix = match.group("prefix")
        prefix = prefix if prefix in {"M", "G", "T"} else prefix.lower()
        canonical = _canonical(match.group("number"), prefix)
        if canonical is not None:
            result.append(Measurement(kind, canonical, match.group(), match.start(), match.end()))
    for match in _RESISTOR.finditer(value):
        if _is_ambiguous_context(value, match.start(), match.end()):
            continue
        marker = match.group(2)
        prefix = "" if marker.lower() == "r" else "M" if marker == "M" else "k"
        canonical = _canonical(f"{match.group(1)}.{match.group(3)}", prefix)
        if canonical is not None:
            result.append(Measurement("resistance", canonical, match.group(), match.start(), match.end()))
    return tuple(sorted(result, key=lambda item: item.start))


def _json_object(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value


def _parameters(value: Any) -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            kind = _PARAMETER_KEYS.get(" ".join(str(key).replace("_", " ").casefold().split()))
            if kind:
                yield kind, nested
            if isinstance(nested, (dict, list)):
                yield from _parameters(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _parameters(nested)


def measurements_for_record(
    source: str, record: Dict[str, Any], aliases: Iterable[str] = (),
) -> Tuple[Tuple[str, str], ...]:
    """Prefer named parameters; use explicit descriptions for missing dimensions."""
    found = set()
    for kind in ("capacitance", "resistance", "inductance"):
        for parsed in parse_measurements(record.get(kind)):
            if parsed.kind == kind:
                found.add((parsed.kind, parsed.value))
    for field in ("attributes", "attributes_dict", "parameters_json", "parameters",
                  "properties_json", "properties", "external_details"):
        for kind, text in _parameters(_json_object(record.get(field))):
            for parsed in parse_measurements(text):
                if parsed.kind == kind:
                    found.add((parsed.kind, parsed.value))
    structured_kinds = {kind for kind, _ in found}
    # Names are not split into values: model numbers often contain 4R7 or 27PF.
    for field in ("value", "name", "mfr", "lib_reference", "mfr_part_number"):
        text = normalize_value_text(record.get(field)).strip()
        parsed = parse_measurements(text)
        if len(parsed) == 1 and parsed[0].start == 0 and parsed[0].end == len(text):
            if parsed[0].kind not in structured_kinds:
                found.add((parsed[0].kind, parsed[0].value))
    fallback_fields = ("description", "note") if source == "inventory" else ("description",)
    for field in fallback_fields:
        for parsed in parse_measurements(record.get(field)):
            if parsed.kind not in structured_kinds:
                found.add((parsed.kind, parsed.value))
    for text in aliases:
        found.update((parsed.kind, parsed.value) for parsed in parse_measurements(text))
    return tuple(sorted(found))
