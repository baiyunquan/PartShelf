# 阶段 4：库存与元件详情

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-03-warehouse.md) · [下一阶段](stage-05-projects-and-loose-parts.md)

**文件：** P/feature/inventory/{InventoryScreen,InventoryDetailScreen,InventoryViewModel,InventoryRepository,InventoryDto,AddPartSheet}.kt；T/InventoryRepositoryTest.kt；IT/InventoryWorkflowTest.kt。
**接口：** list(status?)、search(query,status?)、detail(partId)、add(payload)、updateQuantity(partId,quantity)、updateMeta(payload)、delete(partId)。

- [ ] GET /api/inventory/get_parts_inventory、search?search_key=、get_part_by_id?part_id=；warehouse_status 只用 in_warehouse/not_in_warehouse。
- [ ] 卡片保留名称、来源／编号、封装、厂商、本地数量、项目、位置、照片及状态；现有库存接口返回整组列表，不虚构服务器分页。
- [ ] 详情包含 external_details、描述、参数、资料链接、项目、照片、位置和备注；阶段7增强目录专有详情。
- [ ] POST update_quantity JSON part_id/quantity 设置绝对可用量，操作期间禁止双击；update_meta、delete_part 用现有接口并回读。
- [ ] 手动添加先 /api/libraries/search 选择身份，POST add_part_to_inventory JSON；不在设备创建外部目录记录。项目选择在阶段5完善。
- [ ] 测试不同批次同名、仓储过滤、未知目录、数量超时不盲重发、删除失败、关联页面刷新；提交 `feat: migrate inventory cards and component details`。

**通过条件：** 库存是全部元件总览，供应商库存与本地可用量分开；仓储状态不决定项目归属。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/inventory.html](<../../../../templates/inventory.html>) | 现有网页结构、样式或交互 |
| [templates/component_details.html](<../../../../templates/component_details.html>) | 现有网页结构、样式或交互 |
| [static/js/inventory.js](<../../../../static/js/inventory.js>) | 现有网页结构、样式或交互 |
| [static/js/inventory_recommendation.js](<../../../../static/js/inventory_recommendation.js>) | 现有网页结构、样式或交互 |
| [static/js/component_details.js](<../../../../static/js/component_details.js>) | 现有网页结构、样式或交互 |
| [static/js/component_links.js](<../../../../static/js/component_links.js>) | 现有网页结构、样式或交互 |
| [static/css/inventory.css](<../../../../static/css/inventory.css>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/inventory/get_parts_inventory` | 现有接口；全部库存及 warehouse_status 筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/inventory/search` | 现有接口；search_key 搜索及仓储状态筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/inventory/get_part_by_id` | 现有接口；part_id 详情、照片与项目关联 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `POST /api/inventory/add_part_to_inventory` | 现有接口；按来源和编号添加本地库存 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `POST /api/inventory/update_quantity` | 现有接口；设置绝对可用量 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `POST /api/inventory/update_meta` | 现有接口；修改位置和备注 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `DELETE /api/inventory/delete_part` | 现有接口；删除本地元件 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/libraries/search` | 现有接口；指定来源候选检索 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/warehouse/contents` | 现有接口；配置驱动箱体几何、抽屉内容与未入仓数量 | [app/api/warehouse_api_routes.py](<../../../../app/api/warehouse_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
