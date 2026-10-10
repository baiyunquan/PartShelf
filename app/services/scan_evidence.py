"""Text evidence shared by scan import and AI search; never guesses missing fields."""
import re
import unicodedata

from app.services.electrical_value_service import parse_measurements


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
    brands = {"YAGEO": ("YAGEO", "国巨"), "UNIROYAL": ("UNI-ROYAL", "UNIROYAL", "厚声"),
              "TDK": ("TDK",), "SAMSUNG": ("SAMSUNG", "三星"), "MURATA": ("MURATA", "村田"),
              "NXP": ("NXP", "恩智浦"), "TI": ("TEXAS INSTRUMENTS", "德州仪器")}
    def observed_brand(text):
        return {key for key, aliases in brands.items() if any(
            re.search(r"(?<![A-Z])" + re.escape(alias) + r"(?![A-Z])", normalized(text)) for alias in aliases)}
    expected_brands = observed_brand(component.get("manufacturer"))
    actual_brands = set().union(*(observed_brand(line) for line in lines))
    if expected_brands and actual_brands and actual_brands != expected_brands:
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
    # Compare values only when both label and catalog have explicit electrical units.
    actual = {(m.kind, m.value) for line in lines for m in parse_measurements(line)}
    catalog_texts = [component.get("description", ""), component.get("capacitance", ""),
                     component.get("resistance", ""), component.get("inductance", "")]
    expected = {(m.kind, m.value) for text in catalog_texts for m in parse_measurements(text)}
    for kind in {k for k, _ in actual} & {k for k, _ in expected}:
        if {v for k, v in actual if k == kind} != {v for k, v in expected if k == kind}:
            reasons.append("specifications")
    return {"verified": not reasons, "reasons": list(dict.fromkeys(reasons)), "quantity": quantity,
            "fields": {"model": {"matched": identity_ok and not conflicts, "expected": model,
                                  "text": model if model_found else ", ".join(codes)},
                       "package": {"matched": pkg_ok, "expected": component.get("package"), "text": ", ".join(sorted(observed_pkg))},
                       "quantity": {"matched": "quantity" not in reasons, "expected": quantity, "text": ", ".join(map(str, sorted(counts)))}}}
