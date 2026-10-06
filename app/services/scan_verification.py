"""Parse JLC label payloads and compare independent OCR evidence with a catalog row."""

import json
import re
import unicodedata
from app.services.electrical_value_service import parse_measurements


MIN_CONFIDENCE = 0.90
MIN_MODEL_SIMILARITY = 0.90
MAX_QUANTITY = 2_147_483_647
_KEY = re.compile(r"(?:^|,)\s*([a-z][a-z0-9_]*)\s*:", re.I)
_SIZES = r"(?:0[2468]0[123568]|1008|1206|1210|1812|2010|2512)"
_PACKAGE = re.compile(rf"(?<![A-Z0-9])({_SIZES}|(?:ESOP|SOIC|TSSOP|SSOP|MSOP|SOP|SOT|QFN|DFN|LQFP|QFP|BGA|DIP|TO)\s*-?\s*\d+(?:-\d+)?)(?![A-Z0-9])", re.I)


def normalized(text):
    return unicodedata.normalize("NFKC", str(text or "")).upper().strip()


def compact(text):
    return re.sub(r"[\s_\-/]", "", normalized(text))


def parse_label(raw: str) -> dict:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 4096:
        raise ValueError("Invalid label length")
    raw = raw.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        raise ValueError("Expected a JLC packaging label")
    try:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate label field")
                result[key] = value
            return result
        values = json.loads(raw, object_pairs_hook=unique_pairs)
    except json.JSONDecodeError:
        body = raw[1:-1].strip()
        matches = list(_KEY.finditer(body))
        if not matches or matches[0].start() != 0:
            raise ValueError("Invalid label fields")
        values = {}
        for index, match in enumerate(matches):
            key = match[1].lower()
            if key in values:
                raise ValueError("Duplicate label field")
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            value = body[match.end():end].strip()
            if "," in value or "{" in value or "}" in value:
                raise ValueError("Invalid label value")
            values[key] = None if value == "null" else value
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise ValueError("Invalid label object")
    code = normalized(values.get("pc"))
    if not re.fullmatch(r"C\d{3,10}", code):
        raise ValueError("Invalid LCSC number")
    model = values.get("pm")
    if not isinstance(model, str) or not model.strip() or len(model) > 255:
        raise ValueError("Missing manufacturer model")
    quantity = str(values.get("qty", ""))
    if not re.fullmatch(r"\d+", quantity) or not 1 <= int(quantity) <= MAX_QUANTITY:
        raise ValueError("Package quantity must be a positive integer")
    values.update(pc=f"C{int(code[1:])}", pm=model.strip(), qty=int(quantity))
    return values


def _distance_at_most_one(left, right):
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 1:
        return 2
    if len(left) == len(right):
        return min(2, sum(a != b for a, b in zip(left, right)))
    short, long = (left, right) if len(left) < len(right) else (right, left)
    index = next((i for i, (a, b) in enumerate(zip(short, long)) if a != b), len(short))
    return 1 if short[index:] == long[index + 1:] else 2


def _model_match(expected, lines):
    target = compact(expected)
    best = {"matched": False, "expected": expected, "text": "", "confidence": 0, "similarity": 0}
    if not target:
        return best
    tokens = []
    for line in lines:
        for token in re.findall(r"[A-Z0-9][A-Z0-9._/+\-]*", normalized(line["text"])):
            tokens.append((compact(token), line))
    candidates = [(token, [line]) for token, line in tokens]
    for index in range(len(lines)):
        for count in (1, 2, 3):
            group = lines[index:index + count]
            if len(group) != count:
                continue
            candidates.append((compact(" ".join(line["text"] for line in group)), group))
    matched_token = ""
    for candidate, group in candidates:
        distance = _distance_at_most_one(target, candidate)
        similarity = 1 - distance / max(len(target), len(candidate))
        if distance <= 1 and similarity >= MIN_MODEL_SIMILARITY and similarity > best["similarity"]:
            best = {"matched": True, "expected": expected, "text": " ".join(line["text"] for line in group),
                    "confidence": min(line["confidence"] for line in group), "similarity": similarity}
            matched_token = candidate
    for token, line in tokens:
        logistical = bool(re.fullmatch(r"(?:C\d+|SO\d+|\d{4}[A-Z][A-Z]\d{2}\d{3})", token))
        is_model = len(token) >= 6 and re.search(r"[A-Z]", token) and re.search(r"\d", token)
        if is_model and not logistical and "ROHS" not in token and not parse_measurements(token) and not _PACKAGE.fullmatch(token):
            if token not in matched_token:
                best.update(matched=False, conflict=True)
    return best


def _package_key(text):
    match = _PACKAGE.search(normalized(text))
    return compact(match[1]) if match else compact(text)


def _verify_orientation(label: dict, component: dict | None, ocr: dict) -> dict:
    lines = []
    for item in ocr.get("lines", []):
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("confidence", 0))
        except (ValueError, TypeError):
            continue
        text = str(item.get("text", ""))[:4096]
        if score >= MIN_CONFIDENCE and text:
            lines.append({"text": text, "confidence": score})
    reasons = []
    component = component or {}
    number = label["pc"]
    model = component.get("mfr") or ""
    package = component.get("package") or ""
    codes = []
    packages = []
    quantities = []
    for line in lines:
        text = normalized(line["text"])
        for match in re.finditer(r"(?<![A-Z0-9])C\s*(\d{3,10})(?!\d)", text):
            codes.append((f"C{int(match[1])}", line))
        for match in _PACKAGE.finditer(text):
            packages.append((compact(match[1]), line))
        for match in re.finditer(r"(?:QTY|数量)\s*[:：]?\s*(\d+)(?!\d)", text):
            quantities.append((int(match[1]), line))

    def exact_field(expected, candidates, expected_key=None):
        key = expected if expected_key is None else expected_key
        matching = next((line for value, line in candidates if value == key), None)
        conflicts = any(value != key for value, _ in candidates)
        return {"matched": matching is not None and not conflicts, "expected": expected,
                "text": matching["text"] if matching else "", "confidence": matching["confidence"] if matching else 0,
                "similarity": 1 if matching else 0, "conflict": conflicts}

    fields = {
        "number": exact_field(number, codes),
        "model": _model_match(model, lines),
        "package": exact_field(package, packages, _package_key(package)),
        "quantity": exact_field(label["qty"], quantities),
    }
    if component.get("lcsc") != int(number[1:]):
        fields["number"]["matched"] = False
    if compact(label["pm"]) != compact(model):
        fields["model"].update(matched=False, conflict=True)
    for key in ("number", "model", "package"):
        if not fields[key]["matched"]:
            reasons.append(key)
    if fields["quantity"]["conflict"]:
        reasons.append("quantity")
    return {"verified": not reasons, "fields": fields, "reasons": reasons}


def verify_label(label: dict, component: dict | None, ocr: dict) -> dict:
    candidates = [ocr, *[item for item in ocr.get("alternatives", []) if isinstance(item, dict)]]
    results = [_verify_orientation(label, component, item) for item in candidates]
    selected = next((result for result in results if result["verified"]),
                    max(results, key=lambda result: sum(field["matched"] for field in result["fields"].values())))
    selected = {**selected, "reasons": list(selected["reasons"])}
    # An additional explicit label must not disappear by picking a convenient
    # rotation that happened to miss it.
    for key in ("number", "model", "package", "quantity"):
        if any(result["fields"][key].get("conflict") for result in results):
            selected["verified"] = False
            if key not in selected["reasons"]:
                selected["reasons"].append(key)
    return selected
