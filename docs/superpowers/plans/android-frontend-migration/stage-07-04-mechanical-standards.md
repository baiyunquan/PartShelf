# 子阶段 7.4 机械标准库

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-07-03-kicad.md) · [下一阶段](stage-08-global-and-quick-search.md) · [父阶段与共享导入](stage-07-component-libraries.md)

- [ ] /fasteners/domains、categories、authorities、metadata；列表 q/domain/category/authority/page/page_size。
- [ ] 标准详情、参数／长度表、装配、孔径表；大表横向滚动，身份含标准、公称尺寸及必要长度。
- [ ] POST /fasteners/{standard_code}/specs 添加自定义规格，assembly-guide 与 hole-charts 用既有 API；导入使用服务器生成的 fastener variant ID，不能只传标准号。
- [ ] 测试M2不同长度、公英制、无长度标准、自定义尺寸、同标准两规格；提交 `feat: migrate mechanical standards and variant import screens`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/libraries_fasteners.html](<../../../../templates/libraries_fasteners.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_fasteners_details.html](<../../../../templates/libraries_fasteners_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_fasteners.js](<../../../../static/js/libraries_fasteners.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_fasteners_details.js](<../../../../static/js/libraries_fasteners_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_fasteners.css](<../../../../static/css/libraries_fasteners.css>) | 现有网页结构、样式或交互 |
| [templates/partials/libraries_tabs.html](<../../../../templates/partials/libraries_tabs.html>) | 现有网页结构、样式或交互 |
| [templates/partials/import_modal.html](<../../../../templates/partials/import_modal.html>) | 现有网页结构、样式或交互 |
| [static/js/import_to_inventory_modal.js](<../../../../static/js/import_to_inventory_modal.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/libraries/fasteners/domains` | 现有接口；机械领域 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners/categories` | 现有接口；机械分类 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners/authorities` | 现有接口；标准体系 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners/metadata` | 现有接口；标准元数据 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners` | 现有接口；q/domain/category/authority 及分页 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners/{standard_code}` | 现有接口；标准参数、长度和装配详情 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `POST /api/libraries/fasteners/{standard_code}/specs` | 现有接口；自定义规格 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners/assembly-guide` | 现有接口；装配指导 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/fasteners/hole-charts/{chart_type}` | 现有接口；孔径表 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `POST /api/inventory/add_part_to_inventory` | 现有接口；按来源和编号添加本地库存 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

先阅读父阶段的共享 DTO、Repository、分页上限和统一导入要求。
