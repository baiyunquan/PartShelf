# 阶段 7：四个元件库

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-06-bom-import.md) · [下一阶段](stage-08-global-and-quick-search.md)

**共享文件／接口：** P/feature/libraries/{LibraryRepository,LibraryDto,LibraryListScreen,LibraryDetailScreen,LibraryViewModel,ImportPartSheet}.kt，各库详情子目录；search(source,filters,page)、detail(identity)、importPart(identity,quantity,projectIds)。
**共享测试：** T/LibraryRepositoryTest.kt、IT/LibraryDetailTest.kt。默认25条；电子库最多200，机械库最多100；筛选变化重置页码，缺图不丢行。

## 元件库子阶段

- [子阶段 7.1 JLCParts](stage-07-01-jlcparts.md)
- [子阶段 7.2 Altium](stage-07-02-altium.md)
- [子阶段 7.3 KiCad](stage-07-03-kicad.md)
- [子阶段 7.4 机械标准库](stage-07-04-mechanical-standards.md)

**共享导入：** 复用 POST /api/inventory/add_part_to_inventory JSON，数量、备注与普通项目选择一致；刷新库存。没有仓储照片／放置记录时仍为未入仓。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/libraries_jlcparts.html](<../../../../templates/libraries_jlcparts.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_jlcparts_details.html](<../../../../templates/libraries_jlcparts_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_jlcparts.js](<../../../../static/js/libraries_jlcparts.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_jlcparts_details.js](<../../../../static/js/libraries_jlcparts_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_jlcparts.css](<../../../../static/css/libraries_jlcparts.css>) | 现有网页结构、样式或交互 |
| [templates/partials/libraries_tabs.html](<../../../../templates/partials/libraries_tabs.html>) | 现有网页结构、样式或交互 |
| [templates/partials/import_modal.html](<../../../../templates/partials/import_modal.html>) | 现有网页结构、样式或交互 |
| [static/js/import_to_inventory_modal.js](<../../../../static/js/import_to_inventory_modal.js>) | 现有网页结构、样式或交互 |
| [templates/libraries_altium.html](<../../../../templates/libraries_altium.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_altium_details.html](<../../../../templates/libraries_altium_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_altium.js](<../../../../static/js/libraries_altium.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_altium_details.js](<../../../../static/js/libraries_altium_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_altium.css](<../../../../static/css/libraries_altium.css>) | 现有网页结构、样式或交互 |
| [templates/libraries_kicad.html](<../../../../templates/libraries_kicad.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_kicad_details.html](<../../../../templates/libraries_kicad_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_kicad.js](<../../../../static/js/libraries_kicad.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_kicad_details.js](<../../../../static/js/libraries_kicad_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_kicad.css](<../../../../static/css/libraries_kicad.css>) | 现有网页结构、样式或交互 |
| [templates/libraries_fasteners.html](<../../../../templates/libraries_fasteners.html>) | 现有网页结构、样式或交互 |
| [templates/libraries_fasteners_details.html](<../../../../templates/libraries_fasteners_details.html>) | 现有网页结构、样式或交互 |
| [static/js/libraries_fasteners.js](<../../../../static/js/libraries_fasteners.js>) | 现有网页结构、样式或交互 |
| [static/js/libraries_fasteners_details.js](<../../../../static/js/libraries_fasteners_details.js>) | 现有网页结构、样式或交互 |
| [static/css/libraries_fasteners.css](<../../../../static/css/libraries_fasteners.css>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/libraries/jlcparts/categories` | 现有接口；分类／子分类树 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/jlcparts` | 现有接口；参数、分类、封装、库类型、有货及分页 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/jlcparts/{lcsc}` | 现有接口；精确 C 号详情及动态缓存 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium/categories` | 现有接口；Altium 分类 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium/packages` | 现有接口；Altium 封装 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium` | 现有接口；q/category/package/basic_only 及分页 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/altium/{comp_id}` | 现有接口；Altium 原始整数 ID 详情 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/kicad/libraries` | 现有接口；符号库分类 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/kicad` | 现有接口；q/library 及分页 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/libraries/kicad/{symbol_id}` | 现有接口；符号详情与原始数据 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
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

四个子阶段分别执行；共享文件、导入流程和上限在本文件统一规定。
