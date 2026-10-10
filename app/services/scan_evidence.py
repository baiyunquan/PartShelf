"""Text evidence shared by scan import and AI search; never guesses missing fields."""
import re
import unicodedata
import json
from decimal import Decimal

from app.services.electrical_value_service import parse_measurements, measurements_for_record, normalize_value_text


BRANDS = {"YAGEO": ("YAGEO", "国巨"), "UNIROYAL": ("UNI-ROYAL", "UNIROYAL", "厚声"),
          "TDK": ("TDK",), "SAMSUNG": ("SAMSUNG", "三星"), "MURATA": ("MURATA", "村田"),
          "NXP": ("NXP", "恩智浦"), "TI": ("TI", "TEXAS INSTRUMENTS", "德州仪器"),
          "VISHAY": ("VISHAY", "威世"), "ROHM": ("ROHM", "罗姆"),
          "ONSEMI": ("ONSEMI", "ON SEMICONDUCTOR", "安森美"),
          "STMICROELECTRONICS": ("STMICROELECTRONICS", "意法半导体")}


def manufacturer_key(value):
    text = normalized(value)
    for brand, aliases in BRANDS.items():
        if any(re.search(r"(?<![A-Z])" + re.escape(alias) + r"(?![A-Z])", text) for alias in aliases):
            return brand
    return re.sub(r"[\W_]", "", text)


def electrical_values(lines, kind_hint=None):
    result = {(m.kind, m.value) for line in lines for m in parse_measurements(line)}
    if kind_hint == "resistance":
        for line in lines:
            for token in re.findall(r"(?<![A-Za-z0-9._])\d+(?:\.\d+)?[kKMm](?![A-Za-z0-9_])", line):
                result.update((m.kind, m.value) for m in parse_measurements(token + "Ω"))
    return result


def extra_values(lines):
    """Explicit voltage/current/power/tolerance only, preserving milli versus mega."""
    result = {}
    scales = {"": 0, "p": -12, "n": -9, "u": -6, "m": -3, "k": 3, "K": 3, "M": 6}
    pattern = r"(?<![A-Za-z0-9._-])(\d+(?:\.\d+)?)\s*([pnumkKM]?)\s*([VvAaWw%])(?![A-Za-z0-9_])"
    for line in lines:
        for number, prefix, unit in re.findall(pattern, normalize_value_text(line)):
            value = format(Decimal(number).scaleb(scales[prefix]).normalize(), "f")
            result.setdefault({"V":"voltage", "A":"current", "W":"power", "%":"tolerance"}[unit.upper()], set()).add(value)
    return result


def catalog_specifications(component):
    raw = component.get("raw_item") or {}
    record = {**raw, **{k:v for k,v in component.items() if k != "raw_item"}}
    source = record.get("library_source") or record.get("source") or ("jlcparts" if record.get("lcsc") else "altium")
    source = "jlcparts" if source == "lcsc_dynamic" else source
    values = measurements_for_record(source, record) if source in {"jlcparts", "altium", "kicad"} else ()
    result = {}
    for kind, value in values:
        result.setdefault(kind, set()).add(value)
    texts = [str(record.get(key) or "") for key in ("description", "voltage_rating", "power_rating", "tolerance")]
    for field in ("attributes", "attributes_dict", "parameters", "parameters_json"):
        data = record.get(field)
        if isinstance(data, str):
            try: data = json.loads(data)
            except (ValueError, TypeError): data = None
        if isinstance(data, dict):
            texts.extend(str(v) for v in data.values())
    result.update(extra_values(texts))
    return result


def ocr_model_variant(observed, canonical):
    """One known glyph error in the initial series only; suffixes are immutable."""
    left, right = model_key(observed), model_key(canonical)
    if len(left) != len(right) or len(right) < 10:
        return False
    differences = [i for i,(a,b) in enumerate(zip(left,right)) if a != b]
    pairs = {frozenset(pair) for pair in ("0C", "0O", "1I", "1L", "5S", "8B")}
    return len(differences) == 1 and differences[0] < 6 and frozenset((left[differences[0]], right[differences[0]])) in pairs


def connector_observations(lines):
    """Describe visible connector geometry, without guessing a manufacturer model."""
    observations = {}
    def add(key, value, index, line):
        entry = observations.setdefault(key, {"value": value, "values": [], "evidence": []})
        if value not in entry["values"]:
            entry["values"].append(value)
        entry["value"] = entry["values"][0] if len(entry["values"]) == 1 else None
        evidence = {"line_index": index, "text": line}
        if evidence not in entry["evidence"]:
            entry["evidence"].append(evidence)
    for index, line in enumerate(lines):
        text = normalized(line)
        # Millimeters also describe outlines. Treat them as pitch only in explicit
        # pitch fields or a connector model line with a visible pin count.
        pitch_text = text if (not re.search(r"尺寸|外形|SIZE|DIMENSION", text)
            and re.search(r"\d+\s*P(?![A-Z0-9])", text)) else ""
        pitch_values = re.findall(r"(?<![A-Z0-9.])(\d+(?:\.\d+)?)\s*MM(?![A-Z0-9])", pitch_text)
        pitch_values += re.findall(r"(?:间距|PITCH|\bP\s*=)\s*[:=：]?\s*(\d+(?:\.\d+)?)\s*MM", text)
        for value in pitch_values:
            add("pitch_mm", format(Decimal(value).normalize(), "f"), index, line)
        arrays = list(re.finditer(r"(?<!\d)(\d+)\s*[*X×]\s*(\d+)\s*P(?![A-Z0-9])", text))
        for match in arrays:
            rows, columns = map(int, match.groups())
            add("rows", rows, index, line); add("pins", rows*columns, index, line)
        for match in re.finditer(r"(?<![A-Z0-9])(\d+)\s*P(?![A-Z0-9])", text):
            if not any(m.start() <= match.start() < m.end() for m in arrays):
                add("pins", int(match.group(1)), index, line)
        for pattern, key, value in (
            (r"直插|插件|THROUGH[\s_-]*HOLE", "mounting", "through_hole"),
            (r"卧贴", "mounting", "horizontal_smd"), (r"立贴", "mounting", "vertical_smd"),
            (r"\bSM[DT]\b|贴片", "mounting", "smd"), (r"上接", "contact_side", "top"),
            (r"下接", "contact_side", "bottom"), (r"焊线", "termination", "solder_wire"),
            (r"TYPE[\s_-]*C", "connector_type", "Type-C"), (r"\bRJ45\b", "connector_type", "RJ45"),
            (r"\bFPC\b", "connector_type", "FPC"),
        ):
            if re.search(pattern, text):
                add(key, value, index, line)
        gh = re.search(r"\bGH\s*(\d+\.\d+)", text)
        if gh:
            add("series_label", f"GH{gh.group(1)}", index, line)
    mount = observations.get("mounting")
    if mount and "smd" in mount["values"] and any(v.endswith("_smd") for v in mount["values"]):
        mount["values"].remove("smd")
        mount["value"] = mount["values"][0] if len(mount["values"]) == 1 else None
    return observations


def normalized(text):
    return unicodedata.normalize("NFKC", str(text or "")).upper().strip()


def model_key(text):
    # Spaces may be introduced by OCR. Preserve punctuation and model suffixes.
    return re.sub(r"\s+", "", normalized(text))


def contains_model(text, model):
    key = model_key(model)
    pattern = r"(?<![A-Z0-9])" + r"\s*".join(re.escape(char) for char in key) + r"(?![A-Z0-9])"
    return bool(key and re.search(pattern, normalized(text)))


def lcsc_codes(lines):
    return list(dict.fromkeys(f"C{int(m)}" for line in lines
                for m in re.findall(r"(?<![A-Z0-9])C(\d{3,10})(?![A-Z0-9])", normalized(line))))


PACKAGE_PATTERN = re.compile(
    r"(?<![A-Z0-9])(0201|0402|0603|0805|1008|1206|1210|1812|2010|2512|"
    r"(?:ESOP|SOIC|TSSOP|SSOP|MSOP|SOP|SOT|QFN|DFN|LQFP|QFP|BGA|DIP|TO)\s*-?\s*\d+(?:-\d+)?)(?![A-Z0-9])", re.I)


def package_key(text):
    value = normalized(text)
    if re.fullmatch(r"THROUGH[\s_-]*HOLE|插件|直插|PIN HEADER", value):
        return "THROUGHHOLE"
    if re.fullmatch(r"SURFACE[\s_-]*MOUNT|贴片|SMT|SMD", value):
        return "SMD"
    return re.sub(r"[\s_-]", "", value)


def packages(lines):
    result = [package_key(m) for line in lines for m in PACKAGE_PATTERN.findall(normalized(line))]
    for line in lines:
        if re.search(r"through[\s_-]*hole|插件|直插", line, re.I):
            result.append("THROUGHHOLE")
        elif re.search(r"surface[\s_-]*mount|贴片|\bSMD\b|\bSMT\b", line, re.I):
            result.append("SMD")
    return set(result)


def quantities(lines):
    result = set()
    for line in lines:
        value = normalized(line)
        number = r"([+-]?\d[\d,.]*(?:[ \t]+\d[\d,.]*)*)"
        patterns = (
            r"(?:\bQTY\b|\bQUANTITY\b|数量)\s*[:：=]?\s*([^\s个只件;，]+(?:[ \t]+\d[^\s个只件;，]*)*)",
            r"(?<![A-Z0-9.,+\-])" + number + r"\s*(?:个|只|件|PCS\b|PIECES\b)",
        )
        for pattern in patterns:
            for token in re.findall(pattern, value):
                token = re.sub(r"(?:PCS|PIECES)$", "", token)
                if re.fullmatch(r"\d+", token):
                    result.add(int(token))
                elif re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d{1,3}(?:[ \t]\d{3})+", token):
                    result.add(int(re.sub(r"[, \t]", "", token)))
                else:
                    result.add(-1)  # Unsupported numeric syntax must require review, never import its prefix.
    return result


def model_tokens(lines):
    result = []
    field_pattern = re.compile(r"(?:型号|料号|\bP/N|\bMPN|\bMODEL)\s*[:：]\s*([A-Z0-9._/+\-]+)(.*)")
    has_model_field = any(field_pattern.search(normalized(line)) for line in lines)
    for line in lines:
        text = normalized(line)
        if re.match(r"^(?:柜号|批次|标识|数量|QTY|QUANTITY)\s*[:：]", text):
            continue
        if has_model_field and re.fullmatch(r"A\d{5,}|[A-Z]-\d{2}-\d{2}-\d{2}", text):
            continue
        collapsed = model_key(text)
        # Retain a full spaced OCR model as a single candidate.
        field = field_pattern.search(text)
        if field:
            first, remainder = field.groups()
            # Join broken model segments only; electrical values remain separate evidence.
            for segment in remainder.split():
                if (not re.fullmatch(r"[A-Z0-9._/+\-]+", segment) or parse_measurements(segment)
                        or PACKAGE_PATTERN.fullmatch(segment) or not re.search(r"[A-Z]", segment)):
                    break
                first += segment
            tokens = [first]
        else:
            tokens = ([collapsed] if re.fullmatch(r"[A-Z0-9._/+\-]{4,80}", collapsed) else
                      re.findall(r"(?<![A-Z0-9])[A-Z0-9][A-Z0-9._/+\-]{3,79}", text))
        for token in tokens:
            if has_model_field and not field and re.fullmatch(r"A\d{5,}|[A-Z]-\d{2}-\d{2}-\d{2}", token):
                continue
            if not (re.search(r"[A-Z]", token) and re.search(r"\d", token)):
                continue
            if re.fullmatch(r"C\d{3,10}|S[O0]\d+|\d{4}[-/].*|\d+(?:\.\d+)?(?:MM|PF|NF|UF|UH|MH|V|W|PCS)", token):
                continue
            if "BARCODE" in token or PACKAGE_PATTERN.fullmatch(token):
                continue
            if token not in result:
                result.append(token)
    return result


def verify_text(component, lines):
    """Require a complete model or C identity, explicit quantity, and no hard conflict."""
    raw = component.get("raw_item") or {}
    component = {**raw, **{k:v for k,v in component.items() if k != "raw_item"}}
    model = component.get("mfr_part_number") or component.get("mfr") or component.get("lib_reference") or component.get("name") or ""
    model_found = any(contains_model(line, model) for line in lines)
    codes = lcsc_codes(lines)
    code = component.get("lcsc") or component.get("lcsc_part")
    code = f"C{str(code).lstrip('Cc')}" if code else None
    conflicts = [token for token in model_tokens(lines) if model_key(token) != model_key(model)]
    identity_ok = model_found or (code is not None and codes == [code])
    reasons = []
    if not identity_ok or conflicts:
        reasons.append("model")
    if codes and (not code or codes != [code]):
        reasons.append("number")
    def observed_brand(text):
        return {key for key, aliases in BRANDS.items() if any(
            re.search(r"(?<![A-Z])" + re.escape(alias) + r"(?![A-Z])", normalized(text)) for alias in aliases)}
    expected_brand = manufacturer_key(component.get("manufacturer"))
    actual_brands = set().union(*(observed_brand(line) for line in lines))
    for line in lines:
        match = re.search(r"(?:品牌|制造商|\bBRAND|\bMANUFACTURER)\s*[:：]\s*(.+)", normalized(line))
        if match:
            name = re.sub(r"\([^)]*\)$", "", match.group(1)).strip()
            actual_brands.add(manufacturer_key(name))
    brand_ok = not expected_brand or not actual_brands or actual_brands == {expected_brand}
    if not brand_ok:
        reasons.append("manufacturer")
    expected_pkg = package_key(component.get("package"))
    observed_pkg = packages(lines)
    # Detailed package evidence must agree; generic mounting is not a conflict with a detailed SMD package.
    detailed = observed_pkg - {"SMD", "THROUGHHOLE"}
    usable_pkg = expected_pkg not in {"", "-", "N/A", "NONE"}
    surface_package = bool(re.fullmatch(r"0201|0402|0603|0805|1008|1206|1210|1812|2010|2512|TO252|TO263", expected_pkg)
                           or re.match(r"(?:SOT|SOP|SOIC|TSSOP|SSOP|MSOP|ESOP|QFN|DFN|LQFP|QFP|BGA)\d", expected_pkg))
    mounting = "SMD" if surface_package or expected_pkg == "SMD" else "THROUGHHOLE" if (
        expected_pkg == "THROUGHHOLE" or re.match(r"DIP\d|TO92|TO220", expected_pkg)) else None
    mount_conflict = bool(mounting and (observed_pkg & {"SMD", "THROUGHHOLE"}) - {mounting})
    pkg_ok = not usable_pkg or (expected_pkg in observed_pkg and not (detailed - {expected_pkg}) and not mount_conflict)
    if usable_pkg and not pkg_ok:
        reasons.append("package")
    counts = quantities(lines)
    quantity = next(iter(counts)) if len(counts) == 1 else None
    if quantity is None or not 1 <= quantity <= 2_147_483_647:
        reasons.append("quantity")
        quantity = None
    expected = catalog_specifications(component)
    category = normalized(component.get("category"))
    hint = next((kind for word, kind in (("RESIST", "resistance"), ("电阻", "resistance"),
                    ("CAPAC", "capacitance"), ("电容", "capacitance"), ("INDUCT", "inductance"), ("电感", "inductance")) if word in category), None)
    primary_kinds = set(expected) & {"resistance", "capacitance", "inductance"}
    if hint is None and len(primary_kinds) == 1:
        hint = next(iter(primary_kinds))
    values = electrical_values(lines, hint)
    actual = extra_values(lines)
    for kind, value in values:
        actual.setdefault(kind, set()).add(value)
    actual_primary = set(actual) & {"resistance", "capacitance", "inductance"}
    if primary_kinds and actual_primary - primary_kinds:
        reasons.append("specifications")
    for kind in actual.keys() & expected.keys():
        if actual[kind] != expected[kind]:
            reasons.append("specifications")
    correction = None
    tokens = model_tokens(lines)
    if (not model_found and len(tokens) == 1 and ocr_model_variant(tokens[0], model)
            and hint in {"capacitance", "resistance", "inductance"}
            and expected_brand and actual_brands == {expected_brand} and usable_pkg and pkg_ok
            and hint in actual and hint in expected and actual[hint] == expected[hint]
            and not component.get("retrieval_truncated")):
        correction = {"observed": tokens[0], "canonical": model_key(model)}
        identity_ok = True
        conflicts = []
        reasons = [reason for reason in reasons if reason != "model"]
    line_evidence = lambda predicate: [{"line_index": index, "text": line} for index, line in enumerate(lines) if predicate(line)]
    fields = {
        "model": {"matched": identity_ok and not conflicts, "expected": model,
                  "text": next((line for line in lines if contains_model(line, model)), correction["observed"] if correction else ", ".join(codes)),
                  "evidence": line_evidence(lambda line: contains_model(line, model) or bool(lcsc_codes([line])) or (bool(correction) and contains_model(line, correction["observed"])))},
        "package": {"matched": pkg_ok, "expected": component.get("package"), "text": ", ".join(sorted(observed_pkg)),
                    "evidence": line_evidence(lambda line: bool(packages([line])))},
        "quantity": {"matched": "quantity" not in reasons, "expected": quantity, "text": ", ".join(map(str, sorted(counts))),
                     "evidence": line_evidence(lambda line: bool(quantities([line])))},
        "manufacturer": {"matched": brand_ok if expected_brand and actual_brands else None, "expected": component.get("manufacturer"), "text": ", ".join(sorted(actual_brands)),
                         "evidence": line_evidence(lambda line: bool(observed_brand(line)) or bool(re.search(r"品牌|制造商|BRAND|MANUFACTURER", normalized(line))))},
        "specifications": {"matched": False if "specifications" in reasons else True if actual.keys() & expected.keys() else None,
                           "expected": component.get("description") or ", ".join(str(component.get(k) or "") for k in ("capacitance", "resistance", "inductance")),
                           "expected_values": {k:sorted(v) for k,v in expected.items()},
                           "text": "; ".join(line for line in lines if electrical_values([line], hint) or extra_values([line])),
                           "evidence": line_evidence(lambda line: bool(electrical_values([line], hint) or extra_values([line])))},
    }
    result = {"verified": not reasons, "reasons": list(dict.fromkeys(reasons)), "quantity": quantity, "fields": fields}
    if correction:
        result["model_correction"] = correction
    return result
