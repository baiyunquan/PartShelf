# 阶段 8：全局与快捷搜索

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-07-component-libraries.md) · [下一阶段](stage-09-scan-import-and-local-ocr.md)

**文件：** P/feature/search/{SearchScreen,QuickSearchPanel,SearchViewModel,SearchRepository,SearchDto,BackendRouteMapper}.kt；T/SearchFlowTest.kt、BackendRouteMapperTest.kt；IT/SearchNavigationTest.kt。
**接口：** quick(query)、aggregate(query,tab,page)、mapBackendUrl(url): AppDestination?；tab=all/inventory/jlcparts/altium/kicad/fasteners。

- [ ] GET /api/search/quick?q=、aggregate?q=&tab=&page=&page_size=；顶部300ms防抖，取消旧查询，空输入不请求quick。
- [ ] 概览按网页分组，目录JLCParts先于Altium/KiCad；每组保持服务器相关度与总数，不能按供应商库存跨组重排。
- [ ] 已知网页详情URL映射到原生路由，只传ID／identity；其他链接打开外部浏览器。
- [ ] 复用卡片和ImportPartSheet；返回保留query、tab、页码、滚动。
- [ ] 测试旧响应晚到、精确C号、不同来源同型号、空结果、失效详情、参数编码；提交 `feat: add native global and quick search workflows`。

**通过条件：** 全局／快捷搜索完成后再开始阶段9扫码，手动匹配仍共用服务器查询。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/search.html](<../../../../templates/search.html>) | 现有网页结构、样式或交互 |
| [static/js/search.js](<../../../../static/js/search.js>) | 现有网页结构、样式或交互 |
| [static/css/search.css](<../../../../static/css/search.css>) | 现有网页结构、样式或交互 |
| [templates/partials/navbar.html](<../../../../templates/partials/navbar.html>) | 现有网页结构、样式或交互 |
| [static/js/navbar_search.js](<../../../../static/js/navbar_search.js>) | 现有网页结构、样式或交互 |
| [static/js/component_links.js](<../../../../static/js/component_links.js>) | 现有网页结构、样式或交互 |
| [static/js/import_to_inventory_modal.js](<../../../../static/js/import_to_inventory_modal.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/search/quick` | 现有接口；navbar 即时预览；q | [app/api/search_api_routes.py](<../../../../app/api/search_api_routes.py>) |
| `GET /api/search/aggregate` | 现有接口；q/tab/page/page_size 分组和分页 | [app/api/search_api_routes.py](<../../../../app/api/search_api_routes.py>) |
| `GET /api/libraries/search` | 现有接口；指定来源候选检索 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `POST /api/inventory/add_part_to_inventory` | 现有接口；按来源和编号添加本地库存 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

本阶段完成后才进入阶段 9 扫码入库。
