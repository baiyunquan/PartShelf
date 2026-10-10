# B1：模式、来源与能力接口

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-client-ocr-backend.md](<../2026-10-10-client-ocr-backend.md>)。

[上一阶段](stage-b0-baseline-and-compatibility.md) · [下一阶段](stage-b2-client-ocr-validation-and-cache.md)

**文件：** ocr_mode_service.py、client_api_routes.py、core/config.py、main.py、ocr_api_routes.py；tests/test_ocr_modes.py。
**产出：** 第2、3节定义的配置、能力和请求选择，供Android阶段1连接。

- [ ] 添加模式表测试、默认hybrid、非法配置、能力字段／上限、两种禁用code、能力请求不触发模型／目录查询。
- [ ] 实现OCRMode和capabilities，挂载/api/client；配置schema集中保存，启动时校验。
- [ ] scan新参数保持旧默认；只有非QR来源检查按模式拒绝。client_only下/v1/ocr和/api/ocr/ocr返回409 server_ocr_disabled，不转发8010。
- [ ] 测试不传新字段的旧网页server请求、旧请求QR在client_only仍可用、server_only拒绝client非QR。
- [ ] 运行模式与兼容测试，提交 `feat: add OCR deployment modes and client capabilities`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/scan_import.html](<../../../../templates/scan_import.html>) | 现有网页结构、样式或交互 |
| [static/js/scan_import.js](<../../../../static/js/scan_import.js>) | 现有网页结构、样式或交互 |
| [static/js/scan_label.js](<../../../../static/js/scan_label.js>) | 现有网页结构、样式或交互 |
| [static/css/scan_import.css](<../../../../static/css/scan_import.css>) | 现有网页结构、样式或交互 |
| [templates/partials/navbar.html](<../../../../templates/partials/navbar.html>) | 现有网页结构、样式或交互 |
| [templates/partials/language_switcher.html](<../../../../templates/partials/language_switcher.html>) | 现有网页结构、样式或交互 |
| [static/js/navbar_search.js](<../../../../static/js/navbar_search.js>) | 现有网页结构、样式或交互 |
| [static/js/user_identity.js](<../../../../static/js/user_identity.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/client/capabilities` | 计划新增，当前未实现；OCR 模式、客户端契约及上传限制 | `app/api/client_api_routes.py（计划文件）` |
| `GET /api/scan/projects` | 现有接口；扫码专用项目列表，包含 identity_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/recognize` | 现有接口；照片及二维码；计划增加 client OCR 与 project_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /v1/ocr` | 现有接口；PartShelf 服务器 OCR 兼容转发；client_only 计划禁用 | [app/api/ocr_api_routes.py](<../../../../app/api/ocr_api_routes.py>) |
| `POST /api/ocr/ocr` | 现有接口；PartShelf 服务器 OCR 转发别名 | [app/api/ocr_api_routes.py](<../../../../app/api/ocr_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
