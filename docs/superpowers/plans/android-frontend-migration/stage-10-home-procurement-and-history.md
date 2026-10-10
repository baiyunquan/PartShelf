# 阶段 10：首页、采购清单、项目历史

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-09-scan-import-and-local-ocr.md) · [下一阶段](stage-11-integration-and-apk-delivery.md)

**文件：** P/feature/home/HomeScreen.kt、procurement/{ProcurementScreen,ProcurementRepository}.kt、history/{ProjectHistoryScreen,HistoryRepository,HistoryDto}.kt；IT/RemainingPagesTest.kt。

- [ ] 首页复刻现有介绍、功能卡和入口，显示连接状态，不新增未定义的统计看板。
- [ ] /api/projects/procurement/list显示quantity_available、total_needed、shortage及各项目需求；项目视图用/procurement/project/{id}。
- [ ] /api/projects/history使用username/unattributed/part_id/page/page_size，分页字段是pages，不误用元件库total_pages。
- [ ] 显示操作人、UTC转设备时区、动作、数量前后值和快照；project_exists/part_exists=false保留历史且禁用失效跳转。
- [ ] 完成资料外部打开、保存／分享及可访问性；测试中文用户名、无归属、删除后历史、零缺口和语言切换；提交 `feat: complete home procurement and project history screens`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/home.html](<../../../../templates/home.html>) | 现有网页结构、样式或交互 |
| [static/css/home.css](<../../../../static/css/home.css>) | 现有网页结构、样式或交互 |
| [templates/procurement.html](<../../../../templates/procurement.html>) | 现有网页结构、样式或交互 |
| [static/js/procurement.js](<../../../../static/js/procurement.js>) | 现有网页结构、样式或交互 |
| [static/css/procurement.css](<../../../../static/css/procurement.css>) | 现有网页结构、样式或交互 |
| [templates/project_history.html](<../../../../templates/project_history.html>) | 现有网页结构、样式或交互 |
| [static/js/project_history.js](<../../../../static/js/project_history.js>) | 现有网页结构、样式或交互 |
| [static/css/project_history.css](<../../../../static/css/project_history.css>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/projects/procurement/list` | 现有接口；全局缺口与项目需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/procurement/project/{project_id}` | 现有接口；项目采购需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/history` | 现有接口；成员／无归属／元件历史，分页字段 pages | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
