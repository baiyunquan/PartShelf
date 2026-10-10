# B2：客户端OCR校验、绑定与缓存

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-client-ocr-backend.md](<../2026-10-10-client-ocr-backend.md>)。

[上一阶段](stage-b1-ocr-modes-and-capabilities.md) · [下一阶段](stage-b3-ai-verification-retry-and-idempotency.md)

**文件：** client_ocr_service.py、scan_ocr_cache.py、scan_api_routes.py、scan_import_service.py；tests/test_client_ocr_contract.py、test_client_ocr_scan.py。
**产出：** client图片与结果严格校验、稳定缓存、ScanSession.ocr持久化。

- [ ] 测试真实图片摘要／尺寸、4MiB边界、2000行、4096字符、NaN/Infinity、非法box、未知字段、Spatial无框文本、empty/incomplete/error。
- [ ] 实现规范化，拒绝来源／引擎／版本不支持和图片错配。JSON过大413，其余无效OCR422，错误不留下业务入库记录。
- [ ] 原子store_client_once；测试同图同模型并发首结果复用、不同模型／来源隔离、服务器旧key仍命中；不修改已有缓存JSON。
- [ ] 在创建client会话时保存选定的缓存结果及图片；AI失败后仍有结果可重试，重复request_id返回原会话。
- [ ] mock paddleocr_client和recognize_once为“调用即失败”，验证全部client接收路径零调用；提交 `feat: validate and persist client OCR evidence`。

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
| `POST /api/scan/recognize` | 现有接口；照片及二维码；计划增加 client OCR 与 project_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/history` | 现有接口；扫描状态及已保存证据 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/{scan_id}/image` | 现有接口；扫描原图读取 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /health` | 外部服务；8010 OCR 适配层就绪检查 | [paddleocr_vl/server.py](<../../../../paddleocr_vl/server.py>) |
| `POST /v1/ocr` | 外部服务；8010 OCR 适配层识别；client 路径不得调用 | [paddleocr_vl/server.py](<../../../../paddleocr_vl/server.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

外部 OCR 接口仅用于服务器兼容对照，client 路径必须验证零调用。
