"""Idempotently add scan navigation and bilingual translation entries."""

import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
TEXT = {
    "zh": {
        "title": "扫码入库", "description": "二维码识别后核验包装编号、型号和封装；一致自动入库。",
        "project": "本次连续扫码关联的项目", "project_help": "选项会持续保留；每包独立入库，并直接加入所选项目。",
        "inventory_only": "仅入库存（散件）", "loading_projects": "正在加载项目…", "ready": "可以开始扫码或上传包装照片。",
        "start_camera": "开始连续扫码", "stop_camera": "停止扫码", "camera": "摄像头", "camera_help": "让完整包装标签进入画面。远程访问摄像头需要 HTTPS。",
        "upload": "上传包装照片", "processing": "正在进行 OCR 核验和元件查询…", "decoding": "正在识别二维码…",
        "no_code": "未找到有效的嘉立创包装二维码，请让完整标签清晰入镜。", "multiple_codes": "检测到多个包装二维码，请单独拍摄一张标签。",
        "camera_error": "无法打开摄像头，请检查权限及 HTTPS，或上传照片。", "error": "请求失败，请检查服务后重试。", "too_large": "图片不能超过 10 MiB。",
        "review": "人工核查", "photo": "包装标签照片", "number": "元件编号", "model": "型号", "package": "封装", "quantity": "包装数量", "note": "备注",
        "new_package": "确认这是一包额外的实物（二维码与已入库包装相同）", "confirm_review": "核查后入库", "retry": "重新 OCR 核验",
        "recent": "最近扫码记录", "refresh": "刷新", "empty": "暂无扫码记录。", "imported": "已自动入库", "needs_review": "待人工核查", "duplicate": "包装已扫描，未重复入库",
        "status_processing": "处理中", "status_imported": "已入库", "status_needs_review": "待核查", "status_duplicate": "重复包装",
        "inspect": "查看核查", "inventory_link": "查看库存", "project_link": "查看项目", "warehouse_link": "继续放置到小号抽屉",
        "matched": "匹配", "unmatched": "缺失或冲突", "catalog": "元件库资料", "ocr": "OCR 识别文字", "reason_number": "编号缺失或冲突", "reason_model": "型号缺失或冲突",
        "reason_package": "封装缺失或冲突", "reason_quantity": "数量冲突", "reason_ocr_unavailable": "OCR 服务不可用", "reason_catalog_unavailable": "元件查询或缓存失败",
        "reason_project_unavailable": "原选项目已不存在", "reason_duplicate": "相同包装已入库", "confirm_duplicate": "请确认这是一包额外的实物。",
        "repeat_camera": "扫描另一包相同码包装", "repeat_ready": "下一张相同二维码会送入人工核查，请确认确为额外的一包实物。",
    },
    "en": {
        "title": "Scan Import", "description": "Read a label QR code and verify its number, model and package before automatic import.",
        "project": "Project for continuous scanning", "project_help": "Your selection persists. Each bag becomes a separate inventory entry and is linked to this project.",
        "inventory_only": "Inventory only (Loose Parts)", "loading_projects": "Loading projects…", "ready": "Start scanning or upload a label photograph.",
        "start_camera": "Start continuous scanning", "stop_camera": "Stop scanning", "camera": "Camera", "camera_help": "Keep the entire label in view. Remote camera access requires HTTPS.",
        "upload": "Upload label photograph", "processing": "Verifying OCR evidence and looking up the component…", "decoding": "Reading QR code…",
        "no_code": "No valid JLC packaging QR code found. Capture a clear, complete label.", "multiple_codes": "Multiple packaging QR codes found. Photograph one label at a time.",
        "camera_error": "Camera unavailable. Check permission and HTTPS, or upload a photograph.", "error": "Request failed. Check the service and retry.", "too_large": "Images must not exceed 10 MiB.",
        "review": "Manual review", "photo": "Packaging label photograph", "number": "Component number", "model": "Model", "package": "Package", "quantity": "Bag quantity", "note": "Note",
        "new_package": "This is an additional physical bag with the same QR as an imported bag", "confirm_review": "Import reviewed bag", "retry": "Retry OCR verification",
        "recent": "Recent scans", "refresh": "Refresh", "empty": "No scans yet.", "imported": "Imported automatically", "needs_review": "Manual review required", "duplicate": "Previously scanned bag; no stock added",
        "status_processing": "Processing", "status_imported": "Imported", "status_needs_review": "Needs review", "status_duplicate": "Duplicate bag",
        "inspect": "Review details", "inventory_link": "View inventory", "project_link": "View project", "warehouse_link": "Continue placement in a small drawer",
        "matched": "Matched", "unmatched": "Missing or conflicting", "catalog": "Catalog data", "ocr": "OCR text", "reason_number": "Number missing or conflicting", "reason_model": "Model missing or conflicting",
        "reason_package": "Package missing or conflicting", "reason_quantity": "Quantity conflict", "reason_ocr_unavailable": "OCR service unavailable", "reason_catalog_unavailable": "Catalog lookup or cache failed",
        "reason_project_unavailable": "Original project no longer exists", "reason_duplicate": "This bag is already imported", "confirm_duplicate": "Confirm this is an additional physical bag.",
        "repeat_camera": "Scan another bag with the same QR", "repeat_ready": "The next repeated QR will open manual review. Confirm that it is an additional physical bag.",
    },
}


def migrate():
    for language, translations in TEXT.items():
        path = BASE / "app" / "i18n" / "locales" / (language + ".json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["scan_import"] = translations
        data["app"]["nav_scan_import"] = translations["title"]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    navbar = BASE / "templates" / "partials" / "navbar.html"
    data = navbar.read_bytes().decode()
    text = data.replace("\r\n", "\n")
    if 'href="/scan-import"' not in text:
        marker = "          <li class=\"nav-item mb-2\">\n            <a class=\"nav-link {% if active_page == 'projects' %}"
        insert = "          <li class=\"nav-item mb-2\">\n            <a class=\"nav-link {% if active_page == 'scan_import' %}active{% endif %}\" href=\"/scan-import\">{{ t('app.nav_scan_import') }}</a>\n          </li>\n"
        if marker not in text:
            raise RuntimeError("Navbar insertion point missing")
        text = text.replace(marker, insert + marker, 1)
    navbar.write_text(text, encoding="utf-8")
    inventory = BASE / "templates" / "inventory.html"
    text = inventory.read_text(encoding="utf-8")
    if 'href="/scan-import"' not in text:
        marker = '          <button class="btn btn-outline-secondary disabled" title="Deferred"'
        if marker not in text:
            raise RuntimeError("Inventory insertion point missing")
        text = text.replace(marker, '          <a class="btn btn-outline-primary me-2" href="/scan-import">{{ t(\'app.nav_scan_import\') }}</a>\n' + marker, 1)
        inventory.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    migrate()
