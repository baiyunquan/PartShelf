import pytest

from app.services.scan_verification import parse_label, verify_label


RAW = "{on:SO25112826326,pc:C6119867,pm:CGA0603X7R104K500JT,qty:200,mc:,cc:1,pdi:187264811,hp:11}"
COMPONENT = {"lcsc": 6119867, "mfr": "CGA0603X7R104K500JT", "package": "0603"}


def evidence(*texts, confidence=0.99):
    return {"api_version": "1", "lines": [{"text": text, "confidence": confidence,
            "box": [[0, i * 20], [300, i * 20], [300, i * 20 + 15], [0, i * 20 + 15]]}
            for i, text in enumerate(texts)]}


def test_real_label_handles_unquoted_empty_and_null_fields():
    label = parse_label(RAW)
    assert (label["pc"], label["pm"], label["qty"]) == ("C6119867", COMPONENT["mfr"], 200)
    assert label["mc"] == ""
    assert parse_label(RAW.replace("hp:11", "hp:null"))["hp"] is None


@pytest.mark.parametrize("raw", [RAW.replace("qty:200", "qty:-1"), RAW.replace("qty:200", "qty:2.5"),
    RAW.replace("qty:200", "qty:0"), RAW.replace("pc:C6119867", "pc:javascript:alert(1)"),
    RAW.replace("pc:C6119867", "pc:C6119867,pc:C965815"), "{pc:C6119867,qty:2}"])
def test_invalid_or_ambiguous_labels_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_label(raw)


def test_catalog_number_model_package_are_found_in_ocr_lines():
    result = verify_label(parse_label(RAW), COMPONENT,
                          evidence("C6119867 BD", "CGA0603X7R104K500JT", "0603", "QTY:200个"))
    assert result["verified"]
    assert set(result["fields"]) == {"number", "model", "package", "quantity"}


def test_model_allows_single_ocr_character_noise_and_adjacent_lines():
    result = verify_label(parse_label(RAW), COMPONENT,
                          evidence("C6119867 BD", "CGA0603X7R", "104K5O0JT", "0603"))
    assert result["verified"]
    assert result["fields"]["model"]["similarity"] >= 0.90


@pytest.mark.parametrize("texts,reason", [
    (("C6119868", COMPONENT["mfr"], "0603"), "number"),
    (("C6119867", COMPONENT["mfr"], "0805"), "package"),
    (("C6119867", COMPONENT["mfr"]), "package"),
    (("C6119867", COMPONENT["mfr"], "0603", "QTY:100个"), "quantity"),
    (("C6119867", "C965815", COMPONENT["mfr"], "0603"), "number"),
])
def test_explicit_conflicts_or_missing_fields_require_review(texts, reason):
    result = verify_label(parse_label(RAW), COMPONENT, evidence(*texts))
    assert not result["verified"]
    assert reason in result["reasons"]


def test_model_embedded_size_does_not_count_as_package_evidence():
    assert not verify_label(parse_label(RAW), COMPONENT,
                            evidence("C6119867", COMPONENT["mfr"]))["verified"]


def test_low_confidence_or_catalog_model_conflict_requires_review():
    texts = evidence("C6119867", COMPONENT["mfr"], "0603", confidence=0.80)
    assert not verify_label(parse_label(RAW), COMPONENT, texts)["verified"]
    assert not verify_label(parse_label(RAW), {**COMPONENT, "mfr": "OTHER-0603"},
                            evidence("C6119867", "OTHER-0603", "0603"))["verified"]


def test_alternative_document_orientation_can_recover_a_missing_package():
    ocr = evidence("C6119867", COMPONENT["mfr"], "8090", confidence=0.99)
    ocr["alternatives"] = [evidence("C6119867", COMPONENT["mfr"], "0603")]
    assert verify_label(parse_label(RAW), COMPONENT, ocr)["verified"]


def test_conflicting_label_in_another_orientation_is_not_hidden():
    ocr = evidence("C6119867", COMPONENT["mfr"], "0603")
    ocr["alternatives"] = [evidence("C6119867", "C965815", COMPONENT["mfr"], "0603")]
    assert not verify_label(parse_label(RAW), COMPONENT, ocr)["verified"]


@pytest.mark.parametrize("extra", [COMPONENT["mfr"] + "XYZ", "DIFFERENT12345"])
def test_complete_model_boundaries_and_second_model_conflicts(extra):
    texts = ["C6119867", extra, "0603"]
    if extra.startswith("DIFFERENT"):
        texts.insert(1, COMPONENT["mfr"])
    assert not verify_label(parse_label(RAW), COMPONENT, evidence(*texts))["verified"]
