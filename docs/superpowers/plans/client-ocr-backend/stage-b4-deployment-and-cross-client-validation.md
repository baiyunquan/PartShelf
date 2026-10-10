# B4：部署、启动器与跨端验收

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-client-ocr-backend.md](<../2026-10-10-client-ocr-backend.md>)。

[上一阶段](stage-b3-ai-verification-retry-and-idempotency.md)

**文件：** run_windows.py、run_linux.py、README.md、paddleocr_vl/API.md；tests/test_ocr_launcher_modes.py。
**产出：** 可关闭服务器OCR、保留AI的部署方式，Android阶段9/11实际可用。

- [ ] 两个启动器新增 `--ocr-mode {hybrid,client_only,server_only}`；显式CLI优先于SCAN_OCR_MODE，再默认hybrid；导出实际模式给Web子进程。
- [ ] client_only自动跳过OCR模型文件检查、8010/8083启动和就绪等待；保留AI模型8081/8082与Web。状态输出标明OCR被配置禁用，不显示成必需服务故障。
- [ ] 现有--no-ocr继续只表示“不启动本机OCR”，不强制改为client_only；hybrid + --no-ocr仍可连接远程OCR。任何模式都不随意终止其他用户已启动的OCR进程。
- [ ] mock进程启动测试Windows/Linux模式、非法配置在产生进程副作用前报错、--no-ocr远程部署兼容、AI进程仍启动。
- [ ] 部署示例：`python run_windows.py --ocr-mode client_only`；Linux同理。直接uvicorn部署使用SCAN_OCR_MODE=client_only，并独立启动现有提取／重排服务。
- [ ] 两种请求在hybrid验收；隔离部署停止OCR服务后client_only上传照片+真实本地结果，验证AI／核查／确认／图片读取／仓储仍可用。
- [ ] 验证/api/ocr转发禁用、能力设置与实际模式一致、旧网页默认hybrid无返回结构回归；更新文档样例。
- [ ] 提交 `feat: support client-only OCR deployment with server AI`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/scan_import.html](<../../../../templates/scan_import.html>) | 现有网页结构、样式或交互 |
| [static/js/scan_import.js](<../../../../static/js/scan_import.js>) | 现有网页结构、样式或交互 |
| [static/js/scan_label.js](<../../../../static/js/scan_label.js>) | 现有网页结构、样式或交互 |
| [static/css/scan_import.css](<../../../../static/css/scan_import.css>) | 现有网页结构、样式或交互 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt>) | 现有 APK 基础与测试入口 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/client/capabilities` | 计划新增，当前未实现；OCR 模式、客户端契约及上传限制 | `app/api/client_api_routes.py（计划文件）` |
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
| `POST /v1/chat/completions` | 外部服务；8081 提取与 8082 重排；保留服务器 AI | [app/services/multi_turn_evaluator.py](<../../../../app/services/multi_turn_evaluator.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

启动器另参考 run_windows.py、run_linux.py；client_only 跳过 8010/8083，AI 保留。
