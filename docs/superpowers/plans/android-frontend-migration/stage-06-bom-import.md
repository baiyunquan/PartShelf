# 阶段 6：BOM 导入

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-05-projects-and-loose-parts.md) · [下一阶段](stage-07-component-libraries.md)

**文件：** P/feature/bom/{BomImportScreen,BomImportViewModel,BomRepository,BomDto,BomRowCard,BomMatchReviewSheet,BomDraftStore}.kt；T/BomImportStateTest.kt、BomSubmissionRecoveryTest.kt；IT/BomImportWorkflowTest.kt。
**接口：** preview(file)、suggest(item,query)、createCustom(payload)、import(request)；沿用 confirmed_match，原始行字段保留。

- [ ] Storage Access Framework 选择 CSV/XLSX，并保留网页/API接受的.xls扩展名；POST /api/projects/bom/preview multipart file，服务端解析，不能将 content:// URI 当本地路径。当前openpyxl不能解析真实旧式二进制XLS，应展示服务端错误，不宣称已支持，也不在APK额外实现格式转换。
- [ ] 预览保留 Value、comment、footprint、类型、引脚数、供应商号、MPN、数量、位号、match_reason、conflicts、suggestions 和机械尺寸。
- [ ] /suggest 手动搜索、/custom_part 自定义、候选确认；替代／冲突必须点击确认，全选跳过未绑定与待确认行。
- [ ] 新建／选择普通项目，提交前显示选中与未导入行数；POST /import 保持每次新批次、同次同身份合并、可用量0、BOM数量为需求，不提供覆盖／追加选项。
- [ ] BomDraftStore在私有目录保存预览、连接身份、文件摘要、目标项目ID／新项目名称、确认选择及最小提交记录（本地attemptId、请求JSON摘要、提交时间、状态和收到的回执）。状态为ready/submitting/outcome_unknown/completed，发起POST前先持久化submitting。
- [ ] 超时、取消或连接异常转outcome_unknown；应用恢复时遗留submitting也转outcome_unknown。该状态不能自动重放或因修改文件／目标而清除，显示核查项目入口。只有用户明确“已核查，作为新批次导入”才开启另一attempt；completed保留回执，不能恢复成ready再次发送。
- [ ] 明确这只是防止客户端自动重放，不是后端exactly-once保证：现有BOM请求没有幂等键，不向服务器发送虚构request_id，不凭摘要猜测导入未执行。结果未知时新批次仍可能产生重复记录，界面必须让用户先核查。
- [ ] 固定数据测试27pF候选、220pF/100nF、0603/0402冲突、机械缺尺寸、全选、零库存和重复批次；模拟POST发出后进程退出、超时与重启，验证outcome_unknown不会自动POST或被新文件选择清除。工作簿实测用隔离项目；提交 `feat: migrate BOM preview and confirmed import workflow`。

**通过条件：** 制造商、耐压、误差及替代政策沿用服务器，不在 APK 写第二套匹配规则。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/bom_import.html](<../../../../templates/bom_import.html>) | 现有网页结构、样式或交互 |
| [templates/partials/bom_import_helpers.html](<../../../../templates/partials/bom_import_helpers.html>) | 现有网页结构、样式或交互 |
| [static/js/bom_import.js](<../../../../static/js/bom_import.js>) | 现有网页结构、样式或交互 |
| [static/css/bom_import.css](<../../../../static/css/bom_import.css>) | 现有网页结构、样式或交互 |
| [templates/project_details.html](<../../../../templates/project_details.html>) | 现有网页结构、样式或交互 |
| [static/js/project_details.js](<../../../../static/js/project_details.js>) | 现有网页结构、样式或交互 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `POST /api/projects/bom/preview` | 现有接口；multipart file，服务端解析和预览 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `POST /api/projects/bom/suggest` | 现有接口；原编号／型号／参数候选 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `POST /api/projects/bom/custom_part` | 现有接口；人工自定义元件 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `POST /api/projects/bom/import` | 现有接口；确认后创建新批次；当前没有幂等键 | [app/api/bom_api_routes.py](<../../../../app/api/bom_api_routes.py>) |
| `GET /api/projects/` | 现有接口；项目与散件列表；普通响应不含扫码 identity_token | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |
| `GET /api/projects/{project_id}` | 现有接口；项目／散件详情、可用量和需求 | [app/api/project_api_routes.py](<../../../../app/api/project_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

BOM 当前没有 request_id 幂等接口；结果未知时按本阶段的持久化状态要求人工核查。
