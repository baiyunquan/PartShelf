from io import BytesIO

from openpyxl import Workbook

from app.services.bom_service import parse_bom_file, normalize_header, extract_c_code


def test_normalize_header():
    assert normalize_header("Supplier Part") == "supplier_part"
    assert normalize_header("LCSC Part #") == "supplier_part"
    assert normalize_header("立创编号") == "supplier_part"
    assert normalize_header("Quantity") == "quantity"
    assert normalize_header("数量") == "quantity"
    assert normalize_header("Designator") == "designator"
    assert normalize_header("位号") == "designator"
    assert normalize_header("Footprint") == "footprint"
    assert normalize_header("封装") == "footprint"
    assert normalize_header("Comment") == "comment"
    assert normalize_header("型号") == "comment"
    assert normalize_header("Manufacturer Part") == "manufacturer_part"
    assert normalize_header("厂商型号") == "manufacturer_part"


def test_extract_c_code():
    assert extract_c_code("C318941") == 318941
    assert extract_c_code("c1576") == 1576
    assert extract_c_code("C6119842") == 6119842
    assert extract_c_code("318941") == 318941
    assert extract_c_code("LED_0603-R") is None
    assert extract_c_code(None) is None


def test_parse_xlsx_file():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Quantity", "Comment", "Value", "Primary Category", "Secondary Category",
        "Pin Count", "Designator", "Footprint", "LCSC Part #",
    ])
    sheet.append([2, "27 pF", "27pF", "Capacitors", "MLCC", 2, "C1", "C0603", "C131250"])
    content = BytesIO()
    workbook.save(content)

    rows = parse_bom_file(content.getvalue(), "fixture.xlsx")

    assert len(rows) == 1
    assert rows[0]["quantity"] == 2
    assert rows[0]["comment"] == "27 pF"
    assert rows[0]["value"] == "27pF"
    assert rows[0]["primary_category"] == "Capacitors"
    assert rows[0]["secondary_category"] == "MLCC"
    assert rows[0]["pin_count"] == "2"
    assert rows[0]["designator"] == "C1"
    assert rows[0]["footprint"] == "C0603"
    assert rows[0]["supplier_part"] == "C131250"


def test_parse_csv_file_encodings():
    csv_utf8 = "No.,Quantity,Comment,Designator,Footprint,Supplier Part\n1,5,100nF,C1-C5,C0402,C1576\n2,2,LED,D1-D2,0603,C318941\n"
    rows = parse_bom_file(csv_utf8.encode("utf-8"), "test.csv")
    assert len(rows) == 2
    assert rows[0]["comment"] == "100nF"
    assert rows[0]["quantity"] == 5
    assert rows[0]["supplier_part"] == "C1576"
    assert rows[1]["supplier_part"] == "C318941"

    # Test GBK encoding
    csv_gbk = "序号,数量,型号,位号,封装,立创编号\n1,10,0.1uF,C1-C10,0603,C1576\n"
    rows_gbk = parse_bom_file(csv_gbk.encode("gbk"), "test_gbk.csv")
    assert len(rows_gbk) == 1
    assert rows_gbk[0]["quantity"] == 10
    assert rows_gbk[0]["supplier_part"] == "C1576"
