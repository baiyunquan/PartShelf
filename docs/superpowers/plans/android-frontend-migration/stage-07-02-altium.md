# 子阶段 7.2 Altium

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-07-01-jlcparts.md) · [下一阶段](stage-07-03-kicad.md) · [父阶段与共享导入](stage-07-component-libraries.md)

- [ ] /altium/categories、/altium/packages、/altium，q/category/package/basic_only/page/page_size。
- [ ] /altium/{comp_id} 显示网页已有型号、C号、品牌、封装、电气参数与资料；保留 Altium 整数ID，不改成C号。
- [ ] 测试数字与C前缀目录展示、空字段、不同来源和导入；提交 `feat: migrate Altium library screens`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/libraries_altium.html](<../../../../templates/libraries_altium.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_altium_details.html](<../../../../templates/libraries_altium_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_altium.js](<../../../../static/js/libraries_altium.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_altium_details.js](<../../../../static/js/libraries_altium_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_altium.css](<../../../../static/css/libraries_altium.css>) | 现有网页结构、样式或交互 |
| [templates/partials/libraries_tabs.html](<../../../../templates/partials/libraries_tabs.html>) | 现有网页结构、样式或交互 |
| [templates/partials/import_modal.html](<../../../../templates/partials/import_modal.html>) | 现有网页结构、样式或交互 |
| [static/js/import_to_inventory_modal.js](<../../../../static/js/import_to_inventory_modal.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/libraries/altium/categories` | 现有接口；Altium 分类 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium/packages` | 现有接口；Altium 封装 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium` | 现有接口；q/category/package/basic_only 及分页 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium/{comp_id}` | 现有接口；Altium 原始整数 ID 详情 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `POST /api/inventory/add_part_to_inventory` | 现有接口；按来源和编号添加本地库存 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

先阅读父阶段的共享 DTO、Repository、分页上限和统一导入要求。
