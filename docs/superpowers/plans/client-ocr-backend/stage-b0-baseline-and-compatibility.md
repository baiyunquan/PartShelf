# B0：固定基线与兼容测试

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-client-ocr-backend.md](<../2026-10-10-client-ocr-backend.md>)。

[下一阶段](stage-b1-ocr-modes-and-capabilities.md)

**文件：** 当前扫描/OCR服务与测试；新增tests/test_client_ocr_contract.py中的固定样例辅助、测试图生成函数。
**产出：** 原服务器、QR、人工确认和历史返回结构的可运行基线。

- [ ] 阅读当前paddleocr_vl/API.md、scan_import_service和扫码测试；确认历史旧计划的废弃推理路径不参与本轮。
- [ ] 保存服务器OCR固定JSON、RustO客户端示例、有效／缺数量／多个嘉立创QR、非QR图片、已有历史任务样例。
- [ ] 使用现有测试的临时数据库夹具，记录test_scan_import、test_scan_pipeline、test_scan_ai_contracts、test_scan_warehouse_integration的基线，模型调用mock化。
- [ ] 基线断言有效嘉立创QR零OCR零AI、重复确认只计数一次、已有照片可读、项目快照保护、自定义元件stage1预填保留。
- [ ] 提交 `test: record scan and OCR compatibility baseline`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/scan_import.html](<../../../../templates/scan_import.html>) | 现有网页结构、样式或交互 |
| [static/js/scan_import.js](<../../../../static/js/scan_import.js>) | 现有网页结构、样式或交互 |
| [static/js/scan_label.js](<../../../../static/js/scan_label.js>) | 现有网页结构、样式或交互 |
| [static/css/scan_import.css](<../../../../static/css/scan_import.css>) | 现有网页结构、样式或交互 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt>) | 现有 APK 基础与测试入口 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/scan/projects` | 现有接口；扫码专用项目列表，包含 identity_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/recognize` | 现有接口；照片及二维码；计划增加 client OCR 与 project_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/history` | 现有接口；扫描状态及已保存证据 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/{scan_id}/confirm` | 现有接口；候选／自定义元件、数量、new_package 确认 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/{scan_id}/retry` | 现有接口；复用已保存证据；client 不再次 OCR | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/{scan_id}/image` | 现有接口；扫描原图读取 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /v1/ocr` | 现有接口；PartShelf 服务器 OCR 兼容转发；client_only 计划禁用 | [app/api/ocr_api_routes.py](<../../../../app/api/ocr_api_routes.py>) |
| `POST /api/ocr/ocr` | 现有接口；PartShelf 服务器 OCR 转发别名 | [app/api/ocr_api_routes.py](<../../../../app/api/ocr_api_routes.py>) |
| `GET /health` | 外部服务；8010 OCR 适配层就绪检查 | [paddleocr_vl/server.py](<../../../../paddleocr_vl/server.py>) |
| `POST /v1/ocr` | 外部服务；8010 OCR 适配层识别；client 路径不得调用 | [paddleocr_vl/server.py](<../../../../paddleocr_vl/server.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

核对当前网页行为和 APK 本地结果，不恢复旧 PP-OCRv4 部署。
