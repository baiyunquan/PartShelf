# Android 前端迁移实施计划

> 此目录由 scripts/split_migration_plans.py 程序化拆分。先读本总览，再按阶段文件执行；各阶段尾部附当前前端文件和后端接口。

原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

共享约束、架构／协议及验收要求保留在本文件，阶段正文保留在独立文件中。

生成工具：[split_migration_plans.py](<../../../../scripts/split_migration_plans.py>)。在 PartShelf 根目录运行下列命令；阶段文件由程序维护，直接编辑会在重新生成时被覆盖。

```text
py -3 scripts/split_migration_plans.py
py -3 scripts/split_migration_plans.py --check
```

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 如果执行环境没有该技能，按本文的阶段、接口、检查清单和验收门槛顺序执行。

**Goal:** 将 PartShelf 网页前端迁移为原生 Android APK，保留两个端侧测试入口，完整接入仓储、库存、项目、元件库、搜索和扫码流程。

**Architecture:** 沿用现有 Kotlin + Jetpack Compose 工程，以功能目录组织 Screen、ViewModel 和 Repository，通过统一 HTTP 层访问 PartShelf。服务器负责业务数据、目录查询、BOM 匹配和 AI 辅助；APK 负责界面、二维码、照片采集和本地 OCR，业务数据以服务器为准。

**Tech Stack:** 现有 Compose / Material 3、Coroutines / StateFlow；新增 Retrofit + OkHttp、Gson、Navigation Compose、Preferences DataStore、Coil Compose、CameraX + ZXing Core。保留 RustO + MNN PP-OCRv6 Tiny 和 Qwen 0.5B。新增依赖在阶段 1、2、3、9 验证与现有构建栈兼容后锁定到版本目录，禁止动态版本。

**Spec:** 本文第 1 节是已确认需求；客户端 OCR 的唯一接口规格是 [后端 OCR 改造计划](../client-ocr-backend/README.md) 第 3 节。两篇文档一起交给执行者。

## Global Constraints

- 在对应工程当前主工作树修改，不创建 Git worktree；提交信息使用英文 Conventional Commits。
- Android 工程：`C:/Users/liaic/AndroidStudioProjects/RadioLabRepository`。后端工程：`E:/workspace/RadioLabRepoBackend/PartShelf`。
- 保持 applicationId/namespace=`com.liaic.radiolabrepository`、minSdk=28、compileSdk=35、targetSdk=35、ABI=arm64-v8a；不顺带升级 SDK、AGP 或全部依赖。
- 两个测试入口完整保留：Qwen 0.5B 本地对话、PaddleOCR 本地拍照识别。测试 Qwen 不替代生产业务的服务器 AI。
- 手机列表采用卡片，保留网页主要配色、字段、筛选、排序、操作和提示；参数表可横向滚动，仓储图保持真实尺寸比例。
- 中文／英文使用 Android 字符串资源，禁止 Emoji；Material 向量图标可用。现有测试页中的 Emoji 改为纯文本，功能保持。
- 业务操作需要联网；本地测试、OCR 和扫描草稿可离线。不建立离线库存副本或业务同步系统。
- 上传同一份标准化照片及其 OCR 结果；客户端模式不自动回退服务器 OCR。
- 不下载外部元件数据库到 APK，不复制后端匹配、仓储分组和散件归属算法。
- 不清理业务数据库、模型、AAR、JNI 或第三方源码目录；业务联调使用隔离数据。

## Review Focus

1. 切换服务器／用户名后旧请求与旧数据不能进入新会话：阶段 1 测试。
2. 重复提交、断网及应用恢复不能重复执行 BOM 或增加库存：阶段 4、6、9 测试。
3. 新增箱体和不同抽屉配置不能受固定箱数／抽屉数限制：阶段 3 测试。
4. 图片方向、尺寸和 OCR 框必须基于同一张上传照片：阶段 9 测试。
5. 原生库及大模型不重复初始化、业务首页不加载 Qwen、推理中不释放引擎：阶段 0、2、9、11 测试。

---

## 1. 已确认需求、现状与阶段顺序

### 1.1 阶段顺序

用户已明确将扫码入库放到全局与快捷搜索之后。最终重新编号如下，后续不得按原编号提前实现扫码：

| 阶段 | 交付 | 前置 |
|---|---|---|
| 0 | 基线、资产保护、两个测试入口回归 | 无 |
| 1 | 后端基础连接库 | 0 |
| 2 | UI 雏形、sidebar、设置、测试专区 | 1 |
| 3 | 仓储箱完整页面，首个业务页面 | 2 |
| 4 | 库存和元件详情 | 3 |
| 5 | 项目、项目详情与散件 | 4 |
| 6 | BOM 上传、预览与导入 | 5 |
| 7 | 四个元件库列表和详情 | 6 |
| 8 | 全局与快捷搜索 | 7 |
| 9 | 扫码入库、本地 OCR 与服务器 AI 联调 | 8；后端 B1/B2/B3 |
| 10 | 首页、采购清单、项目历史 | 9 |
| 11 | 全流程回归、性能与 APK 交付 | 10；后端 B4 |

后端 B0/B1 可与 Android 0/1 同期进行；Android 1 至 8 不依赖服务器 OCR。阶段 2 建立设置与首页骨架，阶段 10 完成首页内容。本文计划文件交付时不会执行这些业务阶段。

### 1.2 当前代码基线

- 后端检查日期 2026-10-10、提交 `8eecd87`。开始实现时检查最新差异，更新字段映射；不得重跑历史清库或外部库导入。
- Android 已有 MainActivity/MainApp、ModelManager、OcrManager、OcrScreen，两个测试页用 ModalNavigationDrawer 切换。
- 当前 Qwen 在 Activity 启动时初始化。业务迁移调整为进入测试页时初始化；保留 Vulkan、CPU 回退、流式输出、停止、清空、性能指标。
- OcrManager.recognizeUri 已返回逐行文字、score、矩形 frame；测试页保留拍照、相册、重识别、复制全文／单行、置信度和耗时。
- 当前配置：Gradle 9.2.1、AGP 9.0.1、Compose Kotlin 插件 2.0.21、Compose BOM 2024.09.00。兼容性以实际构建结果验证。
- 当前没有 INTERNET 权限和业务 HTTP 客户端；Android 根目录未初始化 Git；示例 JUnit 测试不能证明两个模型测试页正常。
- 必须保留 app/libs 中的两个 RustO AAR、app/src/main/jniLibs/arm64-v8a、assets/qwen_0.5b、assets/models 和现有 noCompress / JNI packaging。
- 服务器目前为 PaddleOCR-VL-1.5 llama.cpp OCR。旧 2026-10-06 扫码计划中的 PP-OCRv4 部署已过时，以当前 paddleocr_vl/API.md 和代码为准。

### 1.3 页面覆盖矩阵

| 网页／现有入口 | Android destination | 阶段 |
|---|---|---|
| / | Home | 2 骨架、10 完整 |
| /warehouse，抽屉、放置、打印弹窗 | Warehouse | 3 |
| /inventory，手动添加及项目选择 | Inventory | 4 |
| /component_details?part_id= | InventoryDetail(partId) | 4 |
| /projects | Projects | 5 |
| /project_details?project_id=，含散件 | ProjectDetail(projectId) | 5 |
| /bom-import，候选核查和自定义元件 | BomImport(projectId?) | 6 |
| /libraries/jlcparts 及详情 | LibraryList(JlcParts)、LibraryDetail(identity) | 7.1 |
| /libraries/altium 及详情 | LibraryList(Altium)、LibraryDetail(identity) | 7.2 |
| /libraries/kicad 及详情 | LibraryList(KiCad)、LibraryDetail(identity) | 7.3 |
| /libraries/fasteners 及详情、规格／孔径／装配 | LibraryList(Fasteners)、LibraryDetail(identity) | 7.4 |
| /search?q= 和 navbar 即时搜索 | Search(query)、QuickSearchPanel | 8 |
| /scan-import?project_id=，核查、历史与放置 | ScanImport(projectId?) | 9 |
| /procurement | Procurement | 10 |
| /project-history | ProjectHistory(partId?) | 10 |
| 原 APK 对话测试 | QwenTest | 0、2 |
| 原 APK 拍照 OCR 测试 | OcrTest | 0、2、9 |
| 网络、用户、语言设置 | Settings | 1、2 |

## 2. 共享架构、接口与验证方法

### 2.1 文件边界

下文 P=`app/src/main/java/com/liaic/radiolabrepository`，T=`app/src/test/java/com/liaic/radiolabrepository`，IT=`app/src/androidTest/java/com/liaic/radiolabrepository`。

- P/core/network：ApiClient、PartShelfApi、ApiResult、ServerCapabilitiesDto、请求身份、URL 解析。
- P/core/settings：Preferences DataStore 保存服务器根地址、用户名、语言。
- P/core/model：ComponentIdentity、分页类型；功能 DTO 各自保存，不塞入一个巨大 DTO 文件。
- P/core/ui：卡片、筛选、数量输入、参数表、图片、空态、错误、确认弹窗。
- P/navigation：AppDestination、AppNavHost、AppSidebar、返回与页面参数。
- P/feature/{warehouse,inventory,projects,bom,libraries,search,scan,home,procurement,history,tests,settings}：各功能 Screen、ViewModel、Repository 和 DTO。
- 原 ModelManager/OcrManager 通过测试页包装复用；JNI 桥接包名不变。使用单个 :app 模块、手动 AppContainer 注入和 Fake Repository，不增加复杂 DI 框架。
- res/values/strings.xml 中文、res/values-en/strings.xml 英文，禁止 Composable 硬编码业务文案。

### 2.2 固定接口与规则

- `ComponentIdentity(source: String, externalPartId: String)`：外部 ID 始终字符串；本地 partId 为 Long。source 支持 jlcparts/altium/kicad/fasteners/custom。
- `ConnectionSettings(baseUrl: String, username: String, language: String)`：zh/en，baseUrl 为以斜杠结尾的 HTTP(S) 根地址。
- `ApiResult<T>`：Success(data)、HttpFailure(status,message)、NetworkFailure(message)、UnsupportedCapability(message)。CancellationException 继续传播。
- `ApiClient.configure(settings)`、`resolveUrl(pathOrUrl)`、`ConnectionRepository.probe(): ApiResult<ConnectionStatus>`。
- 每页公开单个只读 StateFlow；loading/content/empty/error 状态明确。MutationEvents 发布功能域和变更 ID，成功后相关 Repository 失效并回读服务器。
- 保留 nullable 与额外参数 JsonObject，供应商 stock=-1 表示未知，不改成 0；型号后缀不截断。
- 网络沿用 `username=<UTF-8 percent-encoded value>` Cookie，并附 lang=zh|en。用户名仅为归属信息，不虚构 token 登录。
- 普通读取连接 15s、读取 30s；动态搜索读取 60s、BOM/扫描读取 180s。业务 POST 不隐式重发；扫描用固定 request_id，BOM 超时先核查目标项目。
- 切换服务器或用户名取消旧请求、清空业务内存缓存、重建客户端。扫描草稿保持原连接身份，不自动改投新服务器。
- capabilities 404 时用现有 /api/libraries/status 检测旧服务器；1 至 8 可继续，客户端 OCR 提示不支持。
- capabilities映射api_version/client_ocr_contract_version、ocr_mode=hybrid/client_only/server_only、allowed_ocr_sources和limits。SCAN_OCR_MODE由服务器部署配置；APK不修改该变量。server_only只禁用需要客户端OCR的生产路径，嘉立创QR路径和本地测试仍可运行，不能禁用整个ScanImport页面。
- 增加 INTERNET 权限，支持用户明确配置的局域网 HTTP，HTTPS 保持系统证书验证；禁止 trust-all。相对图片 URL 与 multipart 使用同一客户端根地址。
- 手机主列表用卡片，次要字段展开；参数表可横向滚动。宽度小于 840dp 使用 ModalNavigationDrawer，宽屏常驻侧栏。详情路由只传 ID，不传 Bitmap 或完整 JSON。

### 2.3 新依赖固定起点

| 用途 | Maven坐标与版本 |
|---|---|
| HTTP与Gson转换 | com.squareup.retrofit2:retrofit、converter-gson，均2.11.0 |
| HTTP客户端与模拟服务 | com.squareup.okhttp3:okhttp、mockwebserver，均4.12.0；后者仅testImplementation |
| JSON | com.google.code.gson:gson:2.11.0 |
| 原生导航 | androidx.navigation:navigation-compose、navigation-testing，均2.8.9 |
| ViewModel与生命周期收集 | androidx.lifecycle:lifecycle-viewmodel-compose、lifecycle-runtime-compose，均2.8.7，与已有lifecycle版本一致 |
| 偏好存储 | androidx.datastore:datastore-preferences:1.1.1 |
| 图片 | io.coil-kt:coil-compose:2.7.0 |
| 相机 | androidx.camera:camera-core、camera-camera2、camera-lifecycle、camera-view，均1.4.1 |
| 离线二维码 | com.google.zxing:core:3.5.3 |

这些是实施时的固定起点，不是本轮已完成的构建验证。阶段1引入网络／存储，阶段2引入导航／生命周期／图片，阶段3引入ZXing Core供QR标签编码，阶段9引入CameraX并复用ZXing完成QR扫描；实际构建若证实单项冲突，记录错误、仅调整冲突依赖并重跑对应检查，不整体升级SDK与Compose。

### 2.4 验证命令

Android 工程运行 `./gradlew.bat testDebugUnitTest lintDebug assembleDebug`，连接设备运行 `./gradlew.bat connectedDebugAndroidTest`。真推理与安装使用 arm64 真机／模拟器，不承诺 x86 支持。普通 UI／网络使用 Fake 引擎和 MockWebServer；真实模型单独验收。

每阶段添加有意义的行为测试，运行所属测试与 assembleDebug。纯布局变更不反复运行耗时模型；完整设备回归集中在阶段 11。

## 3. 分阶段实施清单

- [阶段 0：基线与两个测试保护](stage-00-baseline-and-test-protection.md)
- [阶段 1：后端基础连接库](stage-01-backend-connection.md)
- [阶段 2：UI 雏形、sidebar 与测试专区](stage-02-ui-shell-sidebar-and-tests.md)
- [阶段 3：仓储箱页面，首个完整业务页面](stage-03-warehouse.md)
- [阶段 4：库存与元件详情](stage-04-inventory-and-details.md)
- [阶段 5：项目与散件](stage-05-projects-and-loose-parts.md)
- [阶段 6：BOM 导入](stage-06-bom-import.md)
- [阶段 7：四个元件库](stage-07-component-libraries.md)
  - [子阶段 7.1 JLCParts](stage-07-01-jlcparts.md)
  - [子阶段 7.2 Altium](stage-07-02-altium.md)
  - [子阶段 7.3 KiCad](stage-07-03-kicad.md)
  - [子阶段 7.4 机械标准库](stage-07-04-mechanical-standards.md)
- [阶段 8：全局与快捷搜索](stage-08-global-and-quick-search.md)
- [阶段 9：扫码入库、本地 OCR 与服务器 AI](stage-09-scan-import-and-local-ocr.md)
- [阶段 10：首页、采购清单、项目历史](stage-10-home-procurement-and-history.md)
- [阶段 11：整体联调、性能与 APK 交付](stage-11-integration-and-apk-delivery.md)

## 4. API、兼容与接手检查

- 库存API的quantity是本地可用量，项目quantity_needed是需求；目录stock是供应商量。
- 动态目录标记lcsc_dynamic与preferred由服务器管理；库存持久引用使用jlcparts，APK不能另造来源。
- 仓储placement照片仍通过既有multipart接口；客户端OCR上传照片不能绕过放置所需照片。
- 新接口只有配套计划定义的capabilities和扫描新增字段；本文列出的其他路径均复用现有API。
- 项目创建走api_add，历史分页用pages，四个目录的元数据和详情保持独立身份。
- [ ] 每个阶段记录文件、接口、验证结果并做英文提交，不把未完成页面从矩阵删除。
- [ ] 更新基线时区分“现有”与“计划新增”，不要将capabilities当作已部署。
- [ ] 最终交付含APK与配置／安装说明、逐页验收表、两个真实测试记录、客户端OCR联调证明。

参考：[Android Navigation](https://developer.android.com/guide/navigation)、[网络安全配置](https://developer.android.com/privacy-and-security/security-config)、[Compose自适应导航](https://developer.android.com/develop/ui/compose/layouts/adaptive/build-adaptive-navigation)、[Navigation发布记录](https://developer.android.com/jetpack/androidx/releases/navigation)、[DataStore发布记录](https://developer.android.com/jetpack/androidx/releases/datastore)、[CameraX发布记录](https://developer.android.com/jetpack/androidx/releases/camera)、[Coil发布记录](https://coil-kt.github.io/coil/changelog/)、[ZXing 3.5.3](https://github.com/zxing/zxing/releases/tag/zxing-3.5.3)。固定版本以实际工程构建验证，不直接复制官网整套最新依赖。
