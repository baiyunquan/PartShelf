# B3：服务器核验、AI、重试与幂等

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-client-ocr-backend.md](<../2026-10-10-client-ocr-backend.md>)。

[上一阶段](stage-b2-client-ocr-validation-and-cache.md) · [下一阶段](stage-b4-deployment-and-cross-client-validation.md)

**文件：** scan_import_service.py及必要的scan_verification兼容处理；tests/test_client_ocr_scan.py、既有扫描AI／入库测试。
**产出：** client复用当前匹配和确认，全链路不触发服务器OCR。

- [ ] 让verify_scan取得已有client结果，按status执行既有文字／数量／AI流程；server继续recognize_once，服务器engine白名单不放宽。
- [ ] 保留嘉立创二维码权威路径及多码核查；无可靠数量不补1，候选歧义、参数冲突、启发式／AI错误不能自动入库。
- [ ] 返回原verification.stages/field_evidence/candidates/recommended_custom_item，保持完整型号后缀与跨库身份；客户端自报match标记不能绕过服务器比较。
- [ ] /retry只用保存client结果；legacy无source结果仍可读。client_only的旧任务已有文字可继续AI，缺文字不调用OCR。
- [ ] 测试相同request_id并发、重复照片、重复confirm、显式new_package、项目被删／ID复用、离线草稿旧project_token、AI故障及retry，校验库存／项目／历史事务只执行一次；旧token在保存新会话前被拒绝。
- [ ] 读取/api/scan/{id}/image，再用照片走现有warehouse placement验证BLOB读取；无需新增图库或仓储写入接口。
- [ ] 运行客户端和既有扫描回归，提交 `feat: reuse client OCR across scan verification and retries`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/scan_import.html](<../../../../templates/scan_import.html>) | 现有网页结构、样式或交互 |
| [static/js/scan_import.js](<../../../../static/js/scan_import.js>) | 现有网页结构、样式或交互 |
| [static/js/scan_label.js](<../../../../static/js/scan_label.js>) | 现有网页结构、样式或交互 |
| [static/css/scan_import.css](<../../../../static/css/scan_import.css>) | 现有网页结构、样式或交互 |
| [templates/warehouse.html](<../../../../templates/warehouse.html>) | 现有网页结构、样式或交互 |
| [static/js/warehouse.js](<../../../../static/js/warehouse.js>) | 现有网页结构、样式或交互 |
| [static/js/warehouse_placement.js](<../../../../static/js/warehouse_placement.js>) | 现有网页结构、样式或交互 |
| [static/js/warehouse_scan.js](<../../../../static/js/warehouse_scan.js>) | 现有网页结构、样式或交互 |
| [static/css/warehouse.css](<../../../../static/css/warehouse.css>) | 现有网页结构、样式或交互 |
| [static/js/vendor/qrcode-generator.js](<../../../../static/js/vendor/qrcode-generator.js>) | 现有网页结构、样式或交互 |
| [templates/project_history.html](<../../../../templates/project_history.html>) | 现有网页结构、样式或交互 |
| [static/js/project_history.js](<../../../../static/js/project_history.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/scan/projects` | 现有接口；扫码专用项目列表，包含 identity_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/recognize` | 现有接口；照片及二维码；计划增加 client OCR 与 project_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/history` | 现有接口；扫描状态及已保存证据 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/{scan_id}/confirm` | 现有接口；候选／自定义元件、数量、new_package 确认 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/{scan_id}/retry` | 现有接口；复用已保存证据；client 不再次 OCR | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/{scan_id}/image` | 现有接口；扫描原图读取 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/warehouse/contents` | 现有接口；配置驱动箱体几何、抽屉内容与未入仓数量 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/suggestion` | 现有接口；目录元件的放置建议 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/suggestion` | 现有接口；本地元件建议；drawer_type=S/L | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `POST /api/warehouse/parts/{part_id}/placement` | 现有接口；cabinet_id/drawer_code/photo 放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `DELETE /api/warehouse/parts/{part_id}/placement` | 现有接口；移除放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/photo` | 现有接口；仓储照片 BLOB 读取 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/inventory/get_parts_inventory` | 现有接口；全部库存及 warehouse_status 筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `POST /v1/chat/completions` | 外部服务；8081 提取与 8082 重排；保留服务器 AI | [app/services/multi_turn_evaluator.py](<../../../../app/services/multi_turn_evaluator.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
