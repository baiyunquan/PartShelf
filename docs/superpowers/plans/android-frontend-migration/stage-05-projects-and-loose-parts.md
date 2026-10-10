# 阶段 5：项目与散件

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-04-inventory-and-details.md) · [下一阶段](stage-06-bom-import.md)

**文件：** P/feature/projects/{ProjectsScreen,ProjectDetailScreen,ProjectsViewModel,ProjectRepository,ProjectDto,ProjectPicker}.kt；T/ProjectRepositoryTest.kt；IT/ProjectWorkflowTest.kt。
**接口：** list/detail/create/update/delete/addPart/updateNeeded/removePart；is_system/system_key 决定保护，不能按中文名字判断。

- [ ] GET /api/projects/、/{id}；创建使用 JSON POST /api/projects/api_add，不使用返回网页重定向的 Form /add。
- [ ] 实现普通项目 CRUD；详情显示 quantity_available、quantity_needed、shortage；add_part JSON part_id/quantity_needed。
- [ ] 修改需求 POST /{id}/update_part_quantity?part_id=&quantity_needed=；DELETE /{id}/remove_part/{part_id} 只解除关联。
- [ ] 散件显示种类数、total_available_quantity、逐项可用量，禁止改名、删除、需求编辑及导入目标；普通项目选择排除系统项目。
- [ ] ProjectPicker 接入手动添加和 BOM／扫码骨架；测试散件归属变动、只读、删除后的回退和用户名归属；提交 `feat: migrate project management and loose parts views`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/projects.html](<../../../../templates/projects.html>) | 现有网页结构、样式或交互 |
| [templates/project_details.html](<../../../../templates/project_details.html>) | 现有网页结构、样式或交互 |
| [static/js/projects.js](<../../../../static/js/projects.js>) | 现有网页结构、样式或交互 |
| [static/js/project_details.js](<../../../../static/js/project_details.js>) | 现有网页结构、样式或交互 |
| [static/css/projects.css](<../../../../static/css/projects.css>) | 现有网页结构、样式或交互 |
| [static/css/project_details.css](<../../../../static/css/project_details.css>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `POST /api/projects/api_add` | 现有接口；JSON 创建普通项目 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `PUT /api/projects/{project_id}` | 现有接口；修改普通项目 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `DELETE /api/projects/{project_id}` | 现有接口；删除普通项目 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `POST /api/projects/{project_id}/add_part` | 现有接口；关联元件及需求数量 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `POST /api/projects/{project_id}/update_part_quantity` | 现有接口；修改项目需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `DELETE /api/projects/{project_id}/remove_part/{part_id}` | 现有接口；解除关联 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/inventory/get_parts_inventory` | 现有接口；全部库存及 warehouse_status 筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
