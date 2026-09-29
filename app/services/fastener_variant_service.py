"""Canonical inventory references for dimension-specific mechanical standards."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote


FASTENER_VARIANT_PREFIX = "fastener:v1/"
FASTENER_CUSTOM_VARIANT_PREFIX = "fastener:v2/"
_NO_LENGTH = "-"


def _decimal_text(value: Any) -> Optional[str]:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    return format(number.normalize(), "f")


def normalize_nominal(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).upper()
    metric = re.fullmatch(r"M(\d+(?:\.\d+)?)", text)
    if metric:
        number = _decimal_text(metric.group(1))
        return f"M{number}" if number is not None else text
    fraction = re.fullmatch(r"(\d+/\d+)(?:IN|INCH|\")?", text)
    if fraction:
        return f"{fraction.group(1)}in"
    return text


def normalize_length(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", "", str(value or "")).lower()
    if not text:
        return None
    inch = re.fullmatch(r"(\d+(?:\.\d+)?|\d+/\d+)(?:in|inch|\")", text)
    if inch:
        return f"{inch.group(1)}in"
    metric = re.fullmatch(r"(\d+(?:\.\d+)?)(?:mm)?", text)
    if metric:
        number = _decimal_text(metric.group(1))
        return number
    return text.upper()


def build_fastener_variant_id(standard_code: str, nominal: str, length: Any = None) -> str:
    code = str(standard_code or "").strip()
    nominal_key = normalize_nominal(nominal)
    length_key = normalize_length(length) if length not in (None, "") else None
    if not code or not nominal_key:
        raise ValueError("standard_code and nominal are required for a fastener variant")
    parts = (code, nominal_key, length_key or _NO_LENGTH)
    return FASTENER_VARIANT_PREFIX + "/".join(quote(part, safe="") for part in parts)


def parse_fastener_variant_id(external_part_id: str) -> Optional[Dict[str, Optional[str]]]:
    value = str(external_part_id or "")
    if not value.startswith(FASTENER_VARIANT_PREFIX):
        return None
    parts = value[len(FASTENER_VARIANT_PREFIX):].split("/")
    if len(parts) != 3:
        return None
    standard_code, nominal, length = (unquote(part) for part in parts)
    if not standard_code or not nominal:
        return None
    return {
        "standard_code": standard_code,
        "nominal": normalize_nominal(nominal),
        "length": None if length == _NO_LENGTH else normalize_length(length),
    }


def build_custom_fastener_variant_id(standard_code: str, row_key: str) -> str:
    code = str(standard_code or "").strip()
    key = str(row_key or "").strip()
    if not code or not key.startswith("user:"):
        raise ValueError("standard_code and a custom parameter row key are required")
    return FASTENER_CUSTOM_VARIANT_PREFIX + "/".join(
        quote(part, safe="") for part in (code, key)
    )


def parse_custom_fastener_variant_id(external_part_id: str) -> Optional[Dict[str, str]]:
    value = str(external_part_id or "")
    if not value.startswith(FASTENER_CUSTOM_VARIANT_PREFIX):
        return None
    parts = value[len(FASTENER_CUSTOM_VARIANT_PREFIX):].split("/")
    if len(parts) != 2:
        return None
    standard_code, row_key = (unquote(part) for part in parts)
    if not standard_code or not row_key.startswith("user:"):
        return None
    return {"standard_code": standard_code, "row_key": row_key}


def get_fastener_variant(external_part_id: str) -> Optional[Dict[str, Any]]:
    """Hydrate and validate one standard row and optional listed length."""
    custom_identity = parse_custom_fastener_variant_id(external_part_id)
    identity = parse_fastener_variant_id(external_part_id)
    if not custom_identity and not identity:
        return None

    from app.services.external_library_service import get_fastener_detail

    standard_code = (custom_identity or identity)["standard_code"] or ""
    detail = get_fastener_detail(standard_code)
    if not detail:
        return None
    standard = detail["standard"]
    if custom_identity:
        param = next((row for row in detail["param_rows"]
                      if row.get("row_key") == custom_identity["row_key"] and row.get("is_custom")), None)
        if not param:
            return None
        nominal = normalize_nominal(param.get("nominal"))
        selected_length = normalize_length(param.get("custom_length")) if param.get("custom_length") else None
    else:
        nominal = identity["nominal"] or ""
        source_rows = [row for row in detail["param_rows"]
                       if normalize_nominal(row.get("nominal")) == nominal]
        param = next((row for row in source_rows if not row.get("is_custom")), None)
        if param is None:
            param = source_rows[0] if source_rows else None
        selected_length = identity["length"]
    if not param:
        return None

    length = selected_length
    length_row = None
    if standard.get("has_length"):
        if not length:
            return None
        length_row = next((
            row for row in detail["length_rows"]
            if (row.get("row_key") == param.get("row_key") and custom_identity)
            or normalize_length(row.get("custom_length")) == length
            or normalize_length(row.get("key")) == length
        ), None)
        if not length_row:
            return None
    elif length:
        return None

    dimensions = dict(zip(detail["param_titles"], param.get("values") or []))
    length_value = (length_row.get("custom_length") or length_row["key"]) if length_row else None
    selected_variant = {
        "standard_code": standard["standard_code"],
        "nominal": param["nominal"],
        "length": length_value,
        "length_bounds_mm": length_row["lengths"] if length_row else [],
        "row_key": param.get("row_key"),
        "is_custom": bool(param.get("is_custom")),
        "dimensions": dimensions,
    }
    size_label = param["nominal"]
    if length_row:
        size_label += f" × {length_value}"
    if "in" not in size_label.lower() and length_row:
        size_label += " mm"
    if param.get("is_custom"):
        custom_dimensions = ", ".join(
            f"{title}={value}" for title, value in dimensions.items() if value is not None
        )
        if custom_dimensions:
            size_label += f" [{custom_dimensions}]"

    return {
        "standard": standard,
        "param_titles": detail["param_titles"],
        "param_rows": detail["param_rows"],
        "length_titles": detail["length_titles"],
        "length_rows": detail["length_rows"],
        "tap_holes": detail["tap_holes"],
        "assembly_guides": detail["assembly_guides"],
        "selected_variant": selected_variant,
        "summary": {
            "name": f"{standard['standard_code']} {size_label}",
            "manufacturer": "Standard",
            "package": size_label,
            "part_type": standard.get("category_group_zh") or standard.get("category_group") or "Mechanical standard",
            "description": standard.get("description") or "",
        },
    }
