# 阶段 9：扫码入库、本地 OCR 与服务器 AI

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-08-global-and-quick-search.md) · [下一阶段](stage-10-home-procurement-and-history.md)

**前置：** 阶段8；后端B1/B2/B3通过。测试专区继续保留，生产ScanImport页面独立。
**文件：** P/feature/scan/{ScanImportScreen,ScanViewModel,ScanRepository,ScanDto,ScanDraftStore,PhotoNormalizer,ClientOcrAdapter,QrDecoder,ScanReviewSheet}.kt；扩展OcrManager；T/ClientOcrAdapterTest.kt、ScanDraftStoreTest.kt；IT/ScanWorkflowTest.kt。
**接口：** PhotoNormalizer.prepare(uri): PreparedPhoto(file,mime,width,height,sha256)；ClientOcrAdapter.recognize(photo): ClientOcrResultDto；Repository.recognize(draft)/confirm(scanId,payload)/retry(scanId)/history/projects。ScanDraft保存UUID requestId、原服务器／用户名、projectId及服务器返回的projectToken、照片与OCR，位于app私有目录。

- [ ] CameraX提供生产预览／拍照，ZXing Core离线解码QR；旧OCR测试保留TakePicture和相册。
- [ ] 校正EXIF，按比例限制最长边2048，不放大小图，必要时压缩至10MiB内。用同一规范化文件解码、OCR、上传，坐标不基于预览缩略图。
- [ ] 嘉立创二维码按既有解析规则；有效嘉立创码零OCR路径，多个码／数量不完整提交服务器核查。PARTSHELF-WH抽屉码只定位仓储，不作为商品自动入库。
- [ ] RustO推理后台且串行；frame矩形转四点box、score转confidence。Spatial全文非空但items为空时，按配套接口生成无坐标文本行，不能丢弃全文。
- [ ] 上传image、request_id、project_id/project_token、qr_text/qr_texts、ocr_source=client及ocr_result。选了项目必须提交捕获时的identity_token；项目已删除／替换409时保留草稿并重新选择。旧服务器不支持时保留草稿，不回退服务器OCR。
- [ ] 扫码项目选项使用GET /api/scan/projects，其中identity_token保存为projectToken；普通/api/projects/响应不含该字段，不能直接用普通项目列表生成扫码草稿身份快照。
- [ ] 显示processing/needs_review/imported/duplicate、原图、OCR行、AI阶段／证据、候选、冲突；未知字段不显示“通过”，数量缺失不默认1。
- [ ] /confirm使用来源／ID或自定义、quantity、note、new_package；recommended_custom_item预填后可编辑。另一个实体包装需显式确认。
- [ ] 入库成功后复用仓储建议／放置，规范化扫描照片自动选中；已导入库存不等于已入仓。
- [ ] 离线保留草稿，联网手动提交；未知完成状态使用同一request_id。服务器／用户切换不自动改投。
- [ ] history和/retry复用已保存OCR，只重试服务器核验；主动重新拍摄生成新草稿。已导入任务重复确认不再加数量。
- [ ] 测试EXIF／框坐标、Spatial文本、空结果、多QR、数量冲突、AI503、服务器OCR关闭、重复请求／确认、草稿恢复、项目删除、相同标签新包装、照片复用和取消；提交 `feat: integrate local OCR with server-side scan verification`。

**通过条件：** 关闭服务器OCR后完成拍照、本地OCR、服务器AI、核查、入库、照片读取和入仓；两个旧测试仍完整可用。

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
| [APK: app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt>) | 现有 APK 基础与测试入口 |

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
| `GET /api/warehouse/contents` | 现有接口；配置驱动箱体几何、抽屉内容与未入仓数量 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/suggestion` | 现有接口；目录元件的放置建议 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/suggestion` | 现有接口；本地元件建议；drawer_type=S/L | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `POST /api/warehouse/parts/{part_id}/placement` | 现有接口；cabinet_id/drawer_code/photo 放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `DELETE /api/warehouse/parts/{part_id}/placement` | 现有接口；移除放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/photo` | 现有接口；仓储照片 BLOB 读取 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `POST /v1/chat/completions` | 外部服务；8081 提取与 8082 重排；保留服务器 AI | [app/services/multi_turn_evaluator.py](<../../../../app/services/multi_turn_evaluator.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

client 所需 OCR 字段和 project_token 为计划扩展；当前 /recognize 还不能按该新契约接收客户端结果。
