# 阶段 3：仓储箱页面，首个完整业务页面

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-02-ui-shell-sidebar-and-tests.md) · [下一阶段](stage-04-inventory-and-details.md)

**文件：** P/feature/warehouse/{WarehouseScreen,WarehouseViewModel,WarehouseRepository,WarehouseDto,CabinetGeometry,WarehouseLabelPdfWriter}.kt；T/CabinetGeometryTest.kt、WarehouseLabelPdfTest.kt；IT/WarehouseScreenTest.kt。
**接口：** contents()、suggest(partId,drawerType)、place(partId,cabinetId,drawerCode,photo)、remove(partId) 返回 ApiResult；CabinetGeometry.hitTest(xMm,yMm): drawerCode?。

- [ ] 完整映射 GET /api/warehouse/contents 的 cabinets/drawerGroups/drawers、坐标／尺寸／qrPayload、parts、part_count、available_quantity、unplaced_part_count。
- [ ] 配置驱动 Canvas／布局，橘色箱框、白色抽屉、网页占用与选中样式、清晰编号；可用宽度适配、缩放／平移，点击正确逆变换为毫米坐标。
- [ ] 实现箱号切换、尺寸信息、抽屉元件卡、数量、照片和详情跳转；使用稳定 ID，不能按数组下标重算箱号。
- [ ] 未入仓元件选择接库存 API；建议 GET /api/warehouse/parts/{id}/suggestion?drawer_type=S|L，目录预览用 /api/warehouse/suggestion。放置 multipart cabinet_id/drawer_code/photo；移除 DELETE placement。
- [ ] 仓储兼容规则由服务器决定，409 后重读建议；成功后刷新库存与仓储。照片采集和选择使用同一公共照片组件。
- [ ] 以 qrPayload 离线生成 QR；PdfDocument + PrintManager 打印／导出，46×32mm 标签、2mm 间距、4列×8行，每 A4 最多32枚。整箱39枚为两页；支持当前箱／全部箱，分享走 FileProvider。
- [ ] 测试初始3箱、每箱30S+9L、第四个不同箱、缩放点击、唯一稳定二维码、打印不裁切、零库存和不兼容位置；提交 `feat: implement native warehouse cabinet and drawer workflows`。

**通过条件：** 正面395×485比例正确；初始抽屉50×36／110×60，显示深度140，箱深160；载荷如 PARTSHELF-WH:BOX-000:S-01 与网页一致。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/warehouse.html](<../../../../templates/warehouse.html>) | 现有网页结构、样式或交互 |
| [static/js/warehouse.js](<../../../../static/js/warehouse.js>) | 现有网页结构、样式或交互 |
| [static/js/warehouse_placement.js](<../../../../static/js/warehouse_placement.js>) | 现有网页结构、样式或交互 |
| [static/js/warehouse_scan.js](<../../../../static/js/warehouse_scan.js>) | 现有网页结构、样式或交互 |
| [static/css/warehouse.css](<../../../../static/css/warehouse.css>) | 现有网页结构、样式或交互 |
| [static/js/vendor/qrcode-generator.js](<../../../../static/js/vendor/qrcode-generator.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/warehouse/contents` | 现有接口；配置驱动箱体几何、抽屉内容与未入仓数量 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/suggestion` | 现有接口；目录元件的放置建议 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/suggestion` | 现有接口；本地元件建议；drawer_type=S/L | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `POST /api/warehouse/parts/{part_id}/placement` | 现有接口；cabinet_id/drawer_code/photo 放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `DELETE /api/warehouse/parts/{part_id}/placement` | 现有接口；移除放置 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/warehouse/parts/{part_id}/photo` | 现有接口；仓储照片 BLOB 读取 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |
| `GET /api/inventory/get_parts_inventory` | 现有接口；全部库存及 warehouse_status 筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/inventory/search` | 现有接口；search_key 搜索及仓储状态筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/inventory/get_part_by_id` | 现有接口；part_id 详情、照片与项目关联 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

箱体配置另参考 app/warehouse_config.py；仓储规则参考 app/services/warehouse_service.py。
