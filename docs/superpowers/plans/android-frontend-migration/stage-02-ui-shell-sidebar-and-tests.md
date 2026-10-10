# 阶段 2：UI 雏形、sidebar 与测试专区

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[上一阶段](stage-01-backend-connection.md) · [下一阶段](stage-03-warehouse.md)

**文件：** P/navigation/{AppDestination,AppNavHost,AppSidebar}.kt、P/core/ui、P/feature/tests/{QwenTestScreen,OcrTestScreen}.kt、SettingsScreen；MainActivity／资源；IT/AppNavigationTest.kt。
**接口：** 第 1.3 节 destination；测试包装现有管理器，不调用生产 AI。

- [ ] 导航测试覆盖所有入口、详情返回、列表筛选／滚动恢复、断网访问测试专区。
- [ ] sidebar 分业务、四个元件库、设置、测试专区；首页为初始 destination，全部页面建立明确骨架，未完成按钮不假装可用。
- [ ] 建立网页颜色／字号映射、共享卡片和状态组件、中英文文案；测试专区始终可见，不限 debug。
- [ ] 去除 Activity 的 Qwen 自动加载，进入 QwenTest 才初始化。离开生成页先停止，再使用实际 LlmSession.release；RustO.close 不在推理中调用，避免重复初始化与资源竞争。
- [ ] 测试快速切页、重新进入和两个旧入口完整交互；提交 `feat: add Android app shell and preserve local test tools`。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [templates/partials/navbar.html](<../../../../templates/partials/navbar.html>) | 现有网页结构、样式或交互 |
| [templates/partials/language_switcher.html](<../../../../templates/partials/language_switcher.html>) | 现有网页结构、样式或交互 |
| [static/js/navbar_search.js](<../../../../static/js/navbar_search.js>) | 现有网页结构、样式或交互 |
| [static/js/user_identity.js](<../../../../static/js/user_identity.js>) | 现有网页结构、样式或交互 |
| [templates/home.html](<../../../../templates/home.html>) | 现有网页结构、样式或交互 |
| [static/css/home.css](<../../../../static/css/home.css>) | 现有网页结构、样式或交互 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/theme/Theme.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/theme/Theme.kt>) | 现有 APK 基础与测试入口 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/client/capabilities` | 计划新增，当前未实现；OCR 模式、客户端契约及上传限制 | `app/api/client_api_routes.py（计划文件）` |
| `GET /api/libraries/status` | 现有接口；旧服务器连接探针、元件库可用状态 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |
| `GET /api/search/quick` | 现有接口；navbar 即时预览；q | [app/api/search_api_routes.py](<../../../../app/api/search_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

快捷搜索此时仅提供雏形，完整交互在阶段 8；两个测试入口仍离线可用。
