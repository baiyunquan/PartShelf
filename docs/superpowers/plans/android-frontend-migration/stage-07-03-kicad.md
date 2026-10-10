# 子阶段 7.3 KiCad

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-07-02-altium.md) · [下一阶段](stage-07-04-mechanical-standards.md) · [父阶段与共享导入](stage-07-component-libraries.md)

- [ ] /kicad/libraries、/kicad?q=&library=&page=&page_size=、/kicad/{symbol_id}。
- [ ] 展示网页已有名称、库、描述、足迹、引脚／属性和原始S-expression，支持文本复制。
- [ ] 测试无制造型号、空封装、长文本和库存引用导入；提交 `feat: migrate KiCad library screens`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/libraries_kicad.html](<../../../../templates/libraries_kicad.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_kicad_details.html](<../../../../templates/libraries_kicad_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_kicad.js](<../../../../static/js/libraries_kicad.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_kicad_details.js](<../../../../static/js/libraries_kicad_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_kicad.css](<../../../../static/css/libraries_kicad.css>) | 现有网页结构、样式或交互 |
| [templates/partials/libraries_tabs.html](<../../../../templates/partials/libraries_tabs.html>) | 现有网页结构、样式或交互 |
| [templates/partials/import_modal.html](<../../../../templates/partials/import_modal.html>) | 现有网页结构、样式或交互 |
| [static/js/import_to_inventory_modal.js](<../../../../static/js/import_to_inventory_modal.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/libraries/kicad/libraries` | 现有接口；符号库分类 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/kicad` | 现有接口；q/library 及分页 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/kicad/{symbol_id}` | 现有接口；符号详情与原始数据 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `POST /api/inventory/add_part_to_inventory` | 现有接口；按来源和编号添加本地库存 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

先阅读父阶段的共享 DTO、Repository、分页上限和统一导入要求。
