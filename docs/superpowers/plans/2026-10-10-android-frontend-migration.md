# Android 前端迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 如果执行环境没有该技能，按本文的阶段、接口、检查清单和验收门槛顺序执行。

**Goal:** 将 PartShelf 网页前端迁移为原生 Android APK，保留两个端侧测试入口，完整接入仓储、库存、项目、元件库、搜索和扫码流程。

**Architecture:** 沿用现有 Kotlin + Jetpack Compose 工程，以功能目录组织 Screen、ViewModel 和 Repository，通过统一 HTTP 层访问 PartShelf。服务器负责业务数据、目录查询、BOM 匹配和 AI 辅助；APK 负责界面、二维码、照片采集和本地 OCR，业务数据以服务器为准。

**Tech Stack:** 现有 Compose / Material 3、Coroutines / StateFlow；新增 Retrofit + OkHttp、Gson、Navigation Compose、Preferences DataStore、Coil Compose、CameraX + ZXing Core。保留 RustO + MNN PP-OCRv6 Tiny 和 Qwen 0.5B。新增依赖在阶段 1、2、3、9 验证与现有构建栈兼容后锁定到版本目录，禁止动态版本。

**Spec:** 本文第 1 节是已确认需求；客户端 OCR 的唯一接口规格是 [后端 OCR 改造计划](2026-10-10-client-ocr-backend.md) 第 3 节。两篇文档一起交给执行者。

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

### 阶段 0：基线与两个测试保护

**文件：** 现有 MainActivity、ModelManager、OcrManager、OcrScreen；新增 Android docs/migration/baseline.md、native-assets.sha256；T/NativeAssetManifestTest.kt。
**接口：** 保留 ModelManager.initialize/chat/stopGeneration/resetConversation、OcrManager.recognizeUri 和 JNI 包名。

- [ ] 记录配置、AAR/JNI/模型 SHA-256；构建现有 APK，在 arm64 设备离线运行两个测试，记录设备和实际结果。
- [ ] 基线列出流式对话、停止、清空、性能指标、拍照、相册、重新识别、复制、置信度、耗时及错误提示。
- [ ] 若 Android 根目录仍无 Git，初始化当前目录源码版本控制，显式提交源码、配置、wrapper；第三方源码和大模型资产保留原位置并用清单记录，不递归暂存整个工程。
- [ ] 添加资产清单检查；保留 Vulkan 到 CPU 的回退。按需初始化及资源关闭由阶段 2 完成。
- [ ] 验收后提交 `chore: record Android migration baseline and native assets`。

**通过条件：** 两个原入口离线工作，已保存真实设备基线；addition_isCorrect/useAppContext 不能代替该验收。

### 阶段 1：后端基础连接库

**文件：** P/core/network/{ApiClient,PartShelfApi,ApiResult,ConnectionRepository}.kt、P/core/settings/SettingsStore.kt；Manifest 与版本目录；T/ApiClientTest.kt。
**接口：** 第 2.2 节；ServerCapabilitiesDto 与配套后端计划第 3 节一致。

- [ ] MockWebServer 覆盖 baseUrl、中文 Cookie、lang、相对 URL、capabilities 404、503、超时与取消。
- [ ] 实现 DataStore 和客户端；真机填写电脑局域网地址，模拟器开发连接可用 10.0.2.2，不能把手机 127.0.0.1 当后端电脑。
- [ ] 能力接口缺失只允许非客户端 OCR 业务；连接失败与服务器功能不支持分别显示。
- [ ] 测试切换地址／用户时旧请求和旧数据不混入新连接；业务用户名要求在相关提交前检查。
- [ ] 真实后端只读连接验收、单元测试与构建；提交 `feat: add PartShelf Android API connection layer`。

### 阶段 2：UI 雏形、sidebar 与测试专区

**文件：** P/navigation/{AppDestination,AppNavHost,AppSidebar}.kt、P/core/ui、P/feature/tests/{QwenTestScreen,OcrTestScreen}.kt、SettingsScreen；MainActivity／资源；IT/AppNavigationTest.kt。
**接口：** 第 1.3 节 destination；测试包装现有管理器，不调用生产 AI。

- [ ] 导航测试覆盖所有入口、详情返回、列表筛选／滚动恢复、断网访问测试专区。
- [ ] sidebar 分业务、四个元件库、设置、测试专区；首页为初始 destination，全部页面建立明确骨架，未完成按钮不假装可用。
- [ ] 建立网页颜色／字号映射、共享卡片和状态组件、中英文文案；测试专区始终可见，不限 debug。
- [ ] 去除 Activity 的 Qwen 自动加载，进入 QwenTest 才初始化。离开生成页先停止，再使用实际 LlmSession.release；RustO.close 不在推理中调用，避免重复初始化与资源竞争。
- [ ] 测试快速切页、重新进入和两个旧入口完整交互；提交 `feat: add Android app shell and preserve local test tools`。

### 阶段 3：仓储箱页面，首个完整业务页面

**文件：** P/feature/warehouse/{WarehouseScreen,WarehouseViewModel,WarehouseRepository,WarehouseDto,CabinetGeometry,WarehouseLabelPdfWriter}.kt；T/CabinetGeometryTest.kt、WarehouseLabelPdfTest.kt；IT/WarehouseScreenTest.kt。
**接口：** contents()、suggest(partId,drawerType)、place(partId,cabinetId,drawerCode,photo)、remove(partId) 返回 ApiResult；CabinetGeometry.hitTest(xMm,yMm): drawerCode?。

- [ ] 完整映射 GET /api/warehouse/contents 的 cabinets/drawerGroups/drawers、坐标／尺寸／qrPayload、parts、part_count、available_quantity、unplaced_part_count。
- [ ] 配置驱动 Canvas／布局，橘色箱框、白色抽屉、网页占用与选中样式、清晰编号；可用宽度适配、缩放／平移，点击正确逆变换为毫米坐标。
- [ ] 实现箱号切换、尺寸信息、抽屉元件卡、数量、照片和详情跳转；使用稳定 ID，不能按数组下标重算箱号。
- [ ] 未入仓元件选择接库存 API；建议 GET /api/warehouse/parts/{id}/suggestion?drawer_type=S|L，目录预览用 /api/warehouse/suggestion。放置 multipart cabinet_id/drawer_code/photo；移除 DELETE placement。
- [ ] 仓储兼容规则由服务器决定，409 后重读建议；成功后刷新库存与仓储。照片采集和选择使用同一公共照片组件。
- [ ] 以 qrPayload 离线生成 QR；PdfDocument + PrintManager 打印／导出，46×32mm 标签、2mm 间距、4列×8行，每 A4 最多32枚。整箱39枚为两页；支持当前箱／全部箱，分享走 FileProvider。
- [ ] 测试初始3箱、每箱30S+9L、第四个不同箱、缩放点击、唯一稳定二维码、打印不裁切、零库存和不兼容位置；提交 `feat: implement native warehouse cabinet and drawer workflows`。

**通过条件：** 正面395×485比例正确；初始抽屉50×36／110×60，显示深度140，箱深160；载荷如 PARTSHELF-WH:BOX-000:S-01 与网页一致。

### 阶段 4：库存与元件详情

**文件：** P/feature/inventory/{InventoryScreen,InventoryDetailScreen,InventoryViewModel,InventoryRepository,InventoryDto,AddPartSheet}.kt；T/InventoryRepositoryTest.kt；IT/InventoryWorkflowTest.kt。
**接口：** list(status?)、search(query,status?)、detail(partId)、add(payload)、updateQuantity(partId,quantity)、updateMeta(payload)、delete(partId)。

- [ ] GET /api/inventory/get_parts_inventory、search?search_key=、get_part_by_id?part_id=；warehouse_status 只用 in_warehouse/not_in_warehouse。
- [ ] 卡片保留名称、来源／编号、封装、厂商、本地数量、项目、位置、照片及状态；现有库存接口返回整组列表，不虚构服务器分页。
- [ ] 详情包含 external_details、描述、参数、资料链接、项目、照片、位置和备注；阶段7增强目录专有详情。
- [ ] POST update_quantity JSON part_id/quantity 设置绝对可用量，操作期间禁止双击；update_meta、delete_part 用现有接口并回读。
- [ ] 手动添加先 /api/libraries/search 选择身份，POST add_part_to_inventory JSON；不在设备创建外部目录记录。项目选择在阶段5完善。
- [ ] 测试不同批次同名、仓储过滤、未知目录、数量超时不盲重发、删除失败、关联页面刷新；提交 `feat: migrate inventory cards and component details`。

**通过条件：** 库存是全部元件总览，供应商库存与本地可用量分开；仓储状态不决定项目归属。

### 阶段 5：项目与散件

**文件：** P/feature/projects/{ProjectsScreen,ProjectDetailScreen,ProjectsViewModel,ProjectRepository,ProjectDto,ProjectPicker}.kt；T/ProjectRepositoryTest.kt；IT/ProjectWorkflowTest.kt。
**接口：** list/detail/create/update/delete/addPart/updateNeeded/removePart；is_system/system_key 决定保护，不能按中文名字判断。

- [ ] GET /api/projects/、/{id}；创建使用 JSON POST /api/projects/api_add，不使用返回网页重定向的 Form /add。
- [ ] 实现普通项目 CRUD；详情显示 quantity_available、quantity_needed、shortage；add_part JSON part_id/quantity_needed。
- [ ] 修改需求 POST /{id}/update_part_quantity?part_id=&quantity_needed=；DELETE /{id}/remove_part/{part_id} 只解除关联。
- [ ] 散件显示种类数、total_available_quantity、逐项可用量，禁止改名、删除、需求编辑及导入目标；普通项目选择排除系统项目。
- [ ] ProjectPicker 接入手动添加和 BOM／扫码骨架；测试散件归属变动、只读、删除后的回退和用户名归属；提交 `feat: migrate project management and loose parts views`。

### 阶段 6：BOM 导入

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

### 阶段 7：四个元件库

**共享文件／接口：** P/feature/libraries/{LibraryRepository,LibraryDto,LibraryListScreen,LibraryDetailScreen,LibraryViewModel,ImportPartSheet}.kt，各库详情子目录；search(source,filters,page)、detail(identity)、importPart(identity,quantity,projectIds)。
**共享测试：** T/LibraryRepositoryTest.kt、IT/LibraryDetailTest.kt。默认25条；电子库最多200，机械库最多100；筛选变化重置页码，缺图不丢行。

#### 7.1 JLCParts

- [ ] /api/libraries/jlcparts/categories 与 /jlcparts，筛选 q/category/subcategory/package/library_type/in_stock_only/page/page_size。
- [ ] 分类联动、重置、仅有货、原有排序；卡片显示供应商stock、阶梯价、基础／扩展／优选／动态标记。
- [ ] /jlcparts/{lcsc} 显示全部属性、图像、数据手册与目录链接；精确C号动态补全由服务器执行。
- [ ] 测试27pf相关度、C号缓存、stock=-1、零库存和末页；提交 `feat: migrate JLCParts library screens`。

#### 7.2 Altium

- [ ] /altium/categories、/altium/packages、/altium，q/category/package/basic_only/page/page_size。
- [ ] /altium/{comp_id} 显示网页已有型号、C号、品牌、封装、电气参数与资料；保留 Altium 整数ID，不改成C号。
- [ ] 测试数字与C前缀目录展示、空字段、不同来源和导入；提交 `feat: migrate Altium library screens`。

#### 7.3 KiCad

- [ ] /kicad/libraries、/kicad?q=&library=&page=&page_size=、/kicad/{symbol_id}。
- [ ] 展示网页已有名称、库、描述、足迹、引脚／属性和原始S-expression，支持文本复制。
- [ ] 测试无制造型号、空封装、长文本和库存引用导入；提交 `feat: migrate KiCad library screens`。

#### 7.4 机械标准库

- [ ] /fasteners/domains、categories、authorities、metadata；列表 q/domain/category/authority/page/page_size。
- [ ] 标准详情、参数／长度表、装配、孔径表；大表横向滚动，身份含标准、公称尺寸及必要长度。
- [ ] POST /fasteners/{standard_code}/specs 添加自定义规格，assembly-guide 与 hole-charts 用既有 API；导入使用服务器生成的 fastener variant ID，不能只传标准号。
- [ ] 测试M2不同长度、公英制、无长度标准、自定义尺寸、同标准两规格；提交 `feat: migrate mechanical standards and variant import screens`。

**共享导入：** 复用 POST /api/inventory/add_part_to_inventory JSON，数量、备注与普通项目选择一致；刷新库存。没有仓储照片／放置记录时仍为未入仓。

### 阶段 8：全局与快捷搜索

**文件：** P/feature/search/{SearchScreen,QuickSearchPanel,SearchViewModel,SearchRepository,SearchDto,BackendRouteMapper}.kt；T/SearchFlowTest.kt、BackendRouteMapperTest.kt；IT/SearchNavigationTest.kt。
**接口：** quick(query)、aggregate(query,tab,page)、mapBackendUrl(url): AppDestination?；tab=all/inventory/jlcparts/altium/kicad/fasteners。

- [ ] GET /api/search/quick?q=、aggregate?q=&tab=&page=&page_size=；顶部300ms防抖，取消旧查询，空输入不请求quick。
- [ ] 概览按网页分组，目录JLCParts先于Altium/KiCad；每组保持服务器相关度与总数，不能按供应商库存跨组重排。
- [ ] 已知网页详情URL映射到原生路由，只传ID／identity；其他链接打开外部浏览器。
- [ ] 复用卡片和ImportPartSheet；返回保留query、tab、页码、滚动。
- [ ] 测试旧响应晚到、精确C号、不同来源同型号、空结果、失效详情、参数编码；提交 `feat: add native global and quick search workflows`。

**通过条件：** 全局／快捷搜索完成后再开始阶段9扫码，手动匹配仍共用服务器查询。

### 阶段 9：扫码入库、本地 OCR 与服务器 AI

**前置：** 阶段8；后端B1/B2/B3通过。测试专区继续保留，生产ScanImport页面独立。
**文件：** P/feature/scan/{ScanImportScreen,ScanViewModel,ScanRepository,ScanDto,ScanDraftStore,PhotoNormalizer,ClientOcrAdapter,QrDecoder,ScanReviewSheet}.kt；扩展OcrManager；T/ClientOcrAdapterTest.kt、ScanDraftStoreTest.kt；IT/ScanWorkflowTest.kt。
**接口：** PhotoNormalizer.prepare(uri): PreparedPhoto(file,mime,width,height,sha256)；ClientOcrAdapter.recognize(photo): ClientOcrResultDto；Repository.recognize(draft)/confirm(scanId,payload)/retry(scanId)/history/projects。ScanDraft保存UUID requestId、原服务器／用户名、projectId及服务器返回的projectToken、照片与OCR，位于app私有目录。

- [ ] CameraX提供生产预览／拍照，ZXing Core离线解码QR；旧OCR测试保留TakePicture和相册。
- [ ] 校正EXIF，按比例限制最长边2048，不放大小图，必要时压缩至10MiB内。用同一规范化文件解码、OCR、上传，坐标不基于预览缩略图。
- [ ] 嘉立创二维码按既有解析规则；有效嘉立创码零OCR路径，多个码／数量不完整提交服务器核查。PARTSHELF-WH抽屉码只定位仓储，不作为商品自动入库。
- [ ] RustO推理后台且串行；frame矩形转四点box、score转confidence。Spatial全文非空但items为空时，按配套接口生成无坐标文本行，不能丢弃全文。
- [ ] 上传image、request_id、project_id/project_token、qr_text/qr_texts、ocr_source=client及ocr_result。选了项目必须提交捕获时的identity_token；项目已删除／替换409时保留草稿并重新选择。旧服务器不支持时保留草稿，不回退服务器OCR。
- [ ] 扫码项目选项使用GET /api/scan/projects，其中identity_token保存为projectToken；普通/api/projects/响应不含该字段，不能直接用普通项目列表生成扫码草稿身份快照。
- [ ] 显示processing/needs_review/imported/duplicate、原图、OCR行、AI阶段／证据、候选、冲突；未知字段不显示“通过”，数量缺失不默认1。
- [ ] /confirm使用来源／ID或自定义、quantity、note、new_package；recommended_custom_item预填后可编辑。另一个实体包装需显式确认。
- [ ] 入库成功后复用仓储建议／放置，规范化扫描照片自动选中；已导入库存不等于已入仓。
- [ ] 离线保留草稿，联网手动提交；未知完成状态使用同一request_id。服务器／用户切换不自动改投。
- [ ] history和/retry复用已保存OCR，只重试服务器核验；主动重新拍摄生成新草稿。已导入任务重复确认不再加数量。
- [ ] 测试EXIF／框坐标、Spatial文本、空结果、多QR、数量冲突、AI503、服务器OCR关闭、重复请求／确认、草稿恢复、项目删除、相同标签新包装、照片复用和取消；提交 `feat: integrate local OCR with server-side scan verification`。

**通过条件：** 关闭服务器OCR后完成拍照、本地OCR、服务器AI、核查、入库、照片读取和入仓；两个旧测试仍完整可用。

### 阶段 10：首页、采购清单、项目历史

**文件：** P/feature/home/HomeScreen.kt、procurement/{ProcurementScreen,ProcurementRepository}.kt、history/{ProjectHistoryScreen,HistoryRepository,HistoryDto}.kt；IT/RemainingPagesTest.kt。

- [ ] 首页复刻现有介绍、功能卡和入口，显示连接状态，不新增未定义的统计看板。
- [ ] /api/projects/procurement/list显示quantity_available、total_needed、shortage及各项目需求；项目视图用/procurement/project/{id}。
- [ ] /api/projects/history使用username/unattributed/part_id/page/page_size，分页字段是pages，不误用元件库total_pages。
- [ ] 显示操作人、UTC转设备时区、动作、数量前后值和快照；project_exists/part_exists=false保留历史且禁用失效跳转。
- [ ] 完成资料外部打开、保存／分享及可访问性；测试中文用户名、无归属、删除后历史、零缺口和语言切换；提交 `feat: complete home procurement and project history screens`。

### 阶段 11：整体联调、性能与 APK 交付

**文件：** IT/EndToEndMigrationTest.kt、Android docs/migration/acceptance.md及构建／安装说明；修复所属功能文件。

- [ ] 隔离后端／测试库，运行单元、Compose、lint、debug构建和arm64安装；记录基线失败与本轮新增失败。
- [ ] 两种语言逐页截图，与网页核对字段、操作、状态、配色。手机卡片为已确认适配，不要求桌面表格像素完全一致。
- [ ] 联调BOM→新批次→项目／散件→仓储→搜索→采购／历史，以及拍照→本地OCR→服务器AI→入库→入仓。
- [ ] hybrid与client_only均验收；client_only关闭8010/8083，保留8081/8082 AI与Web；真实测试完全离线。
- [ ] 记录启动、500条卡片滚动、切页、拍照／OCR、Qwen的耗时和内存；业务首页无Qwen初始化、离开测试停止生成。不虚构无基线的性能门槛。
- [ ] 运行testDebugUnitTest/lintDebug/assembleDebug/connectedDebugAndroidTest；配置本地发布签名后assembleRelease，签名材料不进Git。输出APK、SHA-256、包名、SDK/ABI、安装步骤与设备限制。
- [ ] 全覆盖验收后提交 `test: verify Android migration and document APK delivery`。

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
