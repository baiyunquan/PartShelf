# 阶段 11：整体联调、性能与 APK 交付

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-10-home-procurement-and-history.md)

**文件：** IT/EndToEndMigrationTest.kt、Android docs/migration/acceptance.md及构建／安装说明；修复所属功能文件。

- [ ] 隔离后端／测试库，运行单元、Compose、lint、debug构建和arm64安装；记录基线失败与本轮新增失败。
- [ ] 两种语言逐页截图，与网页核对字段、操作、状态、配色。手机卡片为已确认适配，不要求桌面表格像素完全一致。
- [ ] 联调BOM→新批次→项目／散件→仓储→搜索→采购／历史，以及拍照→本地OCR→服务器AI→入库→入仓。
- [ ] hybrid与client_only均验收；client_only关闭8010/8083，保留8081/8082 AI与Web；真实测试完全离线。
- [ ] 记录启动、500条卡片滚动、切页、拍照／OCR、Qwen的耗时和内存；业务首页无Qwen初始化、离开测试停止生成。不虚构无基线的性能门槛。
- [ ] 运行testDebugUnitTest/lintDebug/assembleDebug/connectedDebugAndroidTest；配置本地发布签名后assembleRelease，签名材料不进Git。输出APK、SHA-256、包名、SDK/ABI、安装步骤与设备限制。
- [ ] 全覆盖验收后提交 `test: verify Android migration and document APK delivery`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/partials/navbar.html](<../../../../templates/partials/navbar.html>) | 现有网页结构、样式或交互 |
| [templates/partials/language_switcher.html](<../../../../templates/partials/language_switcher.html>) | 现有网页结构、样式或交互 |
| [static/js/navbar_search.js](<../../../../static/js/navbar_search.js>) | 现有网页结构、样式或交互 |
| [static/js/user_identity.js](<../../../../static/js/user_identity.js>) | 现有网页结构、样式或交互 |
| [templates/warehouse.html](<../../../../templates/warehouse.html>) | 现有网页结构、样式或交互 |
| [static/js/warehouse.js](<../../../../static/js/warehouse.js>) | 现有网页结构、样式或交互 |
| [static/js/warehouse_placement.js](<../../../../static/js/warehouse_placement.js>) | 现有网页结构、样式或交互 |
| [static/js/warehouse_scan.js](<../../../../static/js/warehouse_scan.js>) | 现有网页结构、样式或交互 |
| [static/css/warehouse.css](<../../../../static/css/warehouse.css>) | 现有网页结构、样式或交互 |
| [static/js/vendor/qrcode-generator.js](<../../../../static/js/vendor/qrcode-generator.js>) | 现有网页结构、样式或交互 |
| [templates/scan_import.html](<../../../../templates/scan_import.html>) | 现有网页结构、样式或交互 |
| [static/js/scan_import.js](<../../../../static/js/scan_import.js>) | 现有网页结构、样式或交互 |
| [static/js/scan_label.js](<../../../../static/js/scan_label.js>) | 现有网页结构、样式或交互 |
| [static/css/scan_import.css](<../../../../static/css/scan_import.css>) | 现有网页结构、样式或交互 |
| [templates/inventory.html](<../../../../templates/inventory.html>) | 现有网页结构、样式或交互 |
| [templates/projects.html](<../../../../templates/projects.html>) | 现有网页结构、样式或交互 |
| [templates/bom_import.html](<../../../../templates/bom_import.html>) | 现有网页结构、样式或交互 |
| [templates/search.html](<../../../../templates/search.html>) | 现有网页结构、样式或交互 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt>) | 现有 APK 基础与测试入口 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/client/capabilities` | 计划新增，当前未实现；OCR 模式、客户端契约及上传限制 | `app/api/client_api_routes.py（计划文件）` |
| `GET /api/libraries/status` | 现有接口；旧服务器连接探针、元件库可用状态 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/inventory/get_parts_inventory` | 现有接口；全部库存及 warehouse_status 筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/inventory/search` | 现有接口；search_key 搜索及仓储状态筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/inventory/get_part_by_id` | 现有接口；part_id 详情、照片与项目关联 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `POST /api/inventory/add_part_to_inventory` | 现有接口；按来源和编号添加本地库存 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `POST /api/inventory/update_quantity` | 现有接口；设置绝对可用量 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/warehouse/contents` | 现有接口；配置驱动箱体几何、抽屉内容与未入仓数量 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/suggestion` | 现有接口；目录元件的放置建议 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/suggestion` | 现有接口；本地元件建议；drawer_type=S/L | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `POST /api/warehouse/parts/{part_id}/placement` | 现有接口；cabinet_id/drawer_code/photo 放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `DELETE /api/warehouse/parts/{part_id}/placement` | 现有接口；移除放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/photo` | 现有接口；仓储照片 BLOB 读取 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `POST /api/projects/bom/preview` | 现有接口；multipart file，服务端解析和预览 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `POST /api/projects/bom/suggest` | 现有接口；原编号／型号／参数候选 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `POST /api/projects/bom/custom_part` | 现有接口；人工自定义元件 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `POST /api/projects/bom/import` | 现有接口；确认后创建新批次；当前没有幂等键 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `GET /api/search/quick` | 现有接口；navbar 即时预览；q | [app/api/search_api_routes.py](<../../../../app/api/search_api_routes.py>) |
| `GET /api/search/aggregate` | 现有接口；q/tab/page/page_size 分组和分页 | [app/api/search_api_routes.py](<../../../../app/api/search_api_routes.py>) |
| `GET /api/libraries/search` | 现有接口；指定来源候选检索 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/scan/projects` | 现有接口；扫码专用项目列表，包含 identity_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/recognize` | 现有接口；照片及二维码；计划增加 client OCR 与 project_token | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/history` | 现有接口；扫描状态及已保存证据 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/{scan_id}/confirm` | 现有接口；候选／自定义元件、数量、new_package 确认 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /api/scan/{scan_id}/retry` | 现有接口；复用已保存证据；client 不再次 OCR | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `GET /api/scan/{scan_id}/image` | 现有接口；扫描原图读取 | [app/api/scan_api_routes.py](<../../../../app/api/scan_api_routes.py>) |
| `POST /v1/chat/completions` | 外部服务；8081 提取与 8082 重排；保留服务器 AI | [app/services/multi_turn_evaluator.py](<../../../../app/services/multi_turn_evaluator.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
