# 阶段 1：后端基础连接库

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-00-baseline-and-test-protection.md) · [下一阶段](stage-02-ui-shell-sidebar-and-tests.md)

**文件：** P/core/network/{ApiClient,PartShelfApi,ApiResult,ConnectionRepository}.kt、P/core/settings/SettingsStore.kt；Manifest 与版本目录；T/ApiClientTest.kt。
**接口：** 第 2.2 节；ServerCapabilitiesDto 与配套后端计划第 3 节一致。

- [ ] MockWebServer 覆盖 baseUrl、中文 Cookie、lang、相对 URL、capabilities 404、503、超时与取消。
- [ ] 实现 DataStore 和客户端；真机填写电脑局域网地址，模拟器开发连接可用 10.0.2.2，不能把手机 127.0.0.1 当后端电脑。
- [ ] 能力接口缺失只允许非客户端 OCR 业务；连接失败与服务器功能不支持分别显示。
- [ ] 测试切换地址／用户时旧请求和旧数据不混入新连接；业务用户名要求在相关提交前检查。
- [ ] 真实后端只读连接验收、单元测试与构建；提交 `feat: add PartShelf Android API connection layer`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/partials/navbar.html](<../../../../templates/partials/navbar.html>) | 现有网页结构、样式或交互 |
| [templates/partials/language_switcher.html](<../../../../templates/partials/language_switcher.html>) | 现有网页结构、样式或交互 |
| [static/js/navbar_search.js](<../../../../static/js/navbar_search.js>) | 现有网页结构、样式或交互 |
| [static/js/user_identity.js](<../../../../static/js/user_identity.js>) | 现有网页结构、样式或交互 |
| [APK: app/src/main/AndroidManifest.xml](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/AndroidManifest.xml>) | 网络与相机权限基线 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/client/capabilities` | 计划新增，当前未实现；OCR 模式、客户端契约及上传限制 | `app/api/client_api_routes.py（计划文件）` |
| `GET /api/libraries/status` | 现有接口；旧服务器连接探针、元件库可用状态 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/inventory/get_parts_inventory` | 现有接口；全部库存及 warehouse_status 筛选 | [app/api/inventory_api_routes.py](<../../../../app/api/inventory_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。
