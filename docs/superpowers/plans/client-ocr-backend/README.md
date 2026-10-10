# 后端客户端 OCR 与双模式部署实施计划

> 此目录由 scripts/split_migration_plans.py 程序化拆分。先读本总览，再按阶段文件执行；各阶段尾部附当前前端文件和后端接口。

原始完整计划：[2026-10-10-client-ocr-backend.md](<../2026-10-10-client-ocr-backend.md>)。

共享约束、架构／协议及验收要求保留在本文件，阶段正文保留在独立文件中。

生成工具：[split_migration_plans.py](<../../../../scripts/split_migration_plans.py>)。在 PartShelf 根目录运行下列命令；阶段文件由程序维护，直接编辑会在重新生成时被覆盖。

```text
py -3 scripts/split_migration_plans.py
py -3 scripts/split_migration_plans.py --check
```

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 没有该技能时按本文阶段、接口、测试与验收门槛执行。

**Goal:** 让 PartShelf 接收 APK 内置 PaddleOCR 的识别结果，跳过服务器 OCR 后继续完成现有 AI、核验与入库；同时兼容网页服务器 OCR，并允许关闭服务器 OCR 部署。

**Architecture:** 在扫描入口选择 OCR 来源，将已校验的客户端结果规范化为现有 lines[].text 证据格式，持久化后复用现有 verify_scan / multi_turn_service / confirm / import_package。来源与模型版本参与客户端缓存身份；服务器 OCR 的当前协议和历史缓存保持兼容。照片仍上传保存，库存与项目写入规则不由客户端决定。

**Tech Stack:** 当前 FastAPI、Pydantic v2、SQLAlchemy、SQLite、Pillow、现有 PaddleOCR-VL llama.cpp 客户端、ElectronicQwen 提取／重排服务；APK 现有 RustO + MNN PP-OCRv6 Tiny。

**Spec:** 本文第 1、3 节为需求和共享协议；配套 [Android 前端迁移计划](../android-frontend-migration/README.md) 阶段 9 在 Android 全局／快捷搜索完成后实施，依赖本文 B1/B2/B3。

## Global Constraints

- 在 PartShelf 当前主工作树修改，不创建 worktree；英文 Conventional Commits。
- 默认 hybrid：旧网页不传新字段仍使用服务器 OCR；APK 明确提交 client，不静默切回服务器。
- 支持关闭服务器 OCR 的 8010/8083 服务，生产 AI 提取／重排仍在服务器 8081/8082。
- 图片仍需上传用于扫码历史和仓储照片；不能实现成只接收文字、不留照片的入口。
- 嘉立创二维码优先，已有有效二维码分支保留零 OCR、零 AI；缺数量／多码进入核查。
- 保持现有候选、参数证据、数量核验、项目身份、人工确认、幂等和事务规则。
- 不清库、不补导目录、不改前端为另一套匹配政策、不迁移 AI 到 APK。
- 不新增业务表。使用 ScanSession.ocr 和 ScanOCRResult.result JSON 保存新增元数据；历史数据保持可读。
- 不恢复旧 PP-OCRv4/PaddlePaddle 服务；服务器模式继续当前 PaddleOCR-VL 协议。
- 中文／英文文案与文档无 Emoji，提交遵循当前 AGENTS.md。

## Review Focus

1. client 请求及重试绝不能进入 recognize_once / paddleocr_client：B2/B3 断言零调用。
2. 图片哈希、尺寸或文字框不一致时不能绑定到其他照片：B2 校验测试。
3. 相同图像的客户端／服务器／不同模型缓存不串用且不能覆盖旧证据：B2 并发测试。
4. 重复 request_id、确认和同标签另一包装不能重复增加库存：B3 事务测试。
5. client_only 部署不要求 OCR 模型存在，但仍启动 AI；旧网页混合模式和历史扫描可用：B1/B4 测试。

---

## 1. 需求、基线与执行边界

### 1.1 已确认行为

- Android 使用已有本地 RustO + MNN PP-OCRv6 引擎，提交照片、文字行、置信度和坐标。
- 后端保存图片及 OCR 证据，继续用现有目录查询和服务器 AI，返回原扫描结构。
- 三种部署模式：hybrid、client_only、server_only。模式由部署配置决定，请求显式选择来源。
- client 的空结果、失败、冲突进入现有核查流程，缺失／畸形提交明确报错；都不会触发服务器 OCR 补救。
- Android 两个测试入口保留；Qwen 本地对话属于测试工具，不是生产业务提取／重排服务。

### 1.2 当前代码事实

检查日期 2026-10-10，后端提交 8eecd87；真正实现时先检查最新差异。

| 当前文件 | 当前职责 | 本轮改造 |
|---|---|---|
| app/api/scan_api_routes.py | /recognize multipart、history、confirm、retry、image | 新增请求来源／OCR JSON，保持旧参数 |
| app/services/scan_import_service.py | 保存照片、二维码优先、OCR／AI核验、自动／人工入库 | 注入客户端证据，确保重试不重复 OCR |
| app/services/scan_ocr_cache.py | 按图像摘要与模型版本持久缓存服务器 OCR 尝试 | 保留旧算法，增加客户端存储分支 |
| app/services/paddleocr_client.py | 调用8010适配层，检查api_version与服务器engine | 保持服务器协议，不为客户端放宽引擎校验 |
| app/services/multi_turn_search_service.py | 接收文字行进行提取、查询、重排和证据比较 | 继续复用，不接照片做OCR |
| app/models/scan_session.py / scan_ocr_result.py | 扫描快照、结果JSON与唯一缓存键 | JSON增量字段，无新业务表 |
| app/api/ocr_api_routes.py | /v1/ocr、/api/ocr/ocr转发 | 根据部署模式明确禁用服务器OCR入口 |
| run_windows.py / run_linux.py | 启动8010/8083与8081/8082/Web，已有--no-ocr | 增加模式选择，client_only跳过OCR模型与进程 |
| paddleocr_vl/API.md | 当前PaddleOCR-VL及扫描协议 | 补充新契约和部署示例 |

历史 2026-10-06 扫码计划包含已过时的传统 OCR 路径，不恢复那些启动逻辑，以当前代码和 paddleocr_vl/API.md 为准。

### 1.3 非目标与阶段依赖

本计划只改变 OCR 来源接入，不将扫码任务变为新的后台队列，不更改外部库优先级或图片存储架构。图片仍在既有扫描目录保存，入仓照片仍由现有 placement 接口写入 BLOB。

| 阶段 | 交付 | 前置／Android依赖 |
|---|---|---|
| B0 | 基线、固定样例与兼容测试 | 无 |
| B1 | 模式、能力接口、来源选择契约 | B0；供Android阶段1使用 |
| B2 | 客户端结果校验、缓存和保存 | B1 |
| B3 | 核验、AI、重试及幂等联通 | B2；Android阶段9需全部通过 |
| B4 | 启动器、部署、跨端回归 | B3；Android阶段11联调 |

## 2. 模式与请求选择

### 2.1 配置

新增 `SCAN_OCR_MODE`，值为 hybrid/client_only/server_only，默认 hybrid。未知配置使启动明确失败，不能退回另一个模式。

| 模式 | 新非二维码扫描 server 来源 | 新非二维码扫描 client 来源 | 有效嘉立创二维码 | 已保存结果读取／文字重试 |
|---|---|---|---|---|
| hybrid | 允许 | 允许 | 保持既有零OCR／零AI分支 | 允许 |
| client_only | 409 server_ocr_disabled | 允许 | 允许，即使未传新字段 | 允许，不能新调用服务器OCR |
| server_only | 允许 | 409 client_ocr_disabled | 允许，OCR字段忽略 | 允许，复用已保存证据 |

来源字段允许 server/client，默认 server；不根据是否上传JSON猜来源。非二维码 client 请求缺少 ocr_result 为422。server 来源携带 ocr_result 为422，避免业务误以为已使用客户端识别。

二维码分支沿用现有解析与多码判定，不简化为“只要字符串有C号就算二维码”。有效嘉立创二维码、多个可解析嘉立创码和缺有效数量的既有二维码核查分支不依赖OCR来源；照片限制仍然校验。已存在 request_id 按既有幂等语义返回原任务，不重新执行 OCR 或入库。

### 2.2 能力查询

新增 `GET /api/client/capabilities`，不查询目录、不加载模型、不发上游健康探测；这是配置能力，不是推理健康状态：

```json
{
  "api_version": "1",
  "client_ocr_contract_version": "1",
  "ocr_mode": "hybrid",
  "allowed_ocr_sources": ["server", "client"],
  "server_ocr_enabled": true,
  "limits": {
    "max_upload_bytes": 10485760,
    "max_image_pixels": 24000000,
    "max_ocr_result_bytes": 4194304,
    "max_ocr_lines": 2000,
    "max_line_chars": 4096
  },
  "languages": ["zh", "en"]
}
```

client_only 返回 allowed_ocr_sources=["client"]、server_ocr_enabled=false；server_only 仅 ["server"]。HTTP200仅说明 PartShelf 配置可访问，不能宣称OCR或AI模型已就绪。

## 3. Android／后端共享协议（唯一规格）

### 3.1 扫描请求

继续使用 `POST /api/scan/recognize` 的 multipart：

| 字段 | 类型与默认值 | 约定 |
|---|---|---|
| image | 必需文件 | JPEG/PNG/WebP，1字节至10MiB、最多2400万像素；所有来源均上传 |
| request_id | UUID字符串 | APK生成并随草稿持久化；网络未知状态重发同一个ID |
| project_id | 可选项目ID | 沿用既有普通项目验证及身份快照 |
| project_token | 可选UUID字符串 | 本轮新增；APK选择项目时必须提交对应identity_token，防止离线草稿遇到数字ID复用；旧server请求可省略 |
| qr_text | 字符串，默认空 | 单二维码原文 |
| qr_texts | 可选JSON字符串数组 | 最多8个，每个最多4096字符，沿用现有契约 |
| ocr_source | server/client，默认server | 本轮新增；APK提交client |
| ocr_result | 可选JSON字符串 | 本轮新增；非二维码client必须提供 |

API没有新图片上传入口，也不让客户端直接传已匹配的库存或AI结论作为证据。

项目校验在保存新会话前执行：client带project_id必须带project_token，否则422；token与当前项目identity_token不符或项目已删除返回409，不调用OCR／AI、不入库。没有project_id时不能带token。旧server请求省略token保持兼容；任意来源提供token都检查。新增检查不要用importing=True提前持有业务写锁；现有_project只在importing分支比较token，应显式扩展为“提供expected_token时也比较”。

### 3.2 客户端结果示例

```json
{
  "api_version": "1",
  "source": "client",
  "engine": "rusto-mnn",
  "model_version": "ppocrv6-tiny-modelhash-photo-v1",
  "status": "complete",
  "image_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "image": {"width": 1200, "height": 800, "rotation_degrees": 0},
  "confidence_source": "provided_by_engine",
  "lines": [
    {"text": "AO3400C", "confidence": 0.98,
     "box": [[20, 30], [240, 30], [240, 70], [20, 70]]},
    {"text": "QTY: 5", "confidence": 0.97,
     "box": [[20, 90], [200, 90], [200, 125], [20, 125]]}
  ],
  "raw_text": "AO3400C\nQTY: 5",
  "elapsed_ms": 320,
  "error": null
}
```

示例哈希是占位内容，测试必须计算真实上传字节的摘要。model_version 使用 `ppocrv6-tiny-<当前模型AAR SHA-256前16字符>-photo-v1`；模型或预处理变化更换版本，不把每次扫描UUID当模型版本。

### 3.3 校验与规范化

- 用Pydantic v2严格模型：api_version="1"、source="client"、engine="rusto-mnn"；model_version为1至128字符，status为complete/incomplete/error；未知字段拒绝，禁止接受verified或selected_component等结论字段。
- OCR JSON UTF-8编码最多4MiB；最多2000行；每行text为字符串，最多4096字符，不能为布尔或数值。非空文字保留内部空格、型号后缀、符号与单位；不在入口执行MPN纠错。
- image_sha256须为64位小写十六进制且等于上传字节SHA-256；width/height为正整数且等于Pillow读到的上传图尺寸，rotation_degrees固定0。
- APK先校正EXIF／规范化再OCR和上传；上传图片不应遗留未应用的EXIF方向。后端不再旋转或缩放客户端照片来“修正”坐标。
- confidence允许null或0至1的有限数字，不接收NaN/Infinity；box允许null或4个二维点，每个坐标有限且在图像边界内，允许小数。
- 普通Structured结果confidence_source=provided_by_engine。Spatial全文结果由APK分行，confidence/box=null、confidence_source=not_provided_by_model；不能因items为空丢掉全文。
- raw_text由规范化后的lines按换行连接重建；不让矛盾的raw_text成为第二套匹配证据。elapsed_ms为非负整数，error为null或最长128字符错误码。
- status=complete但无非空行合法，进入needs_review/ocr_empty。incomplete/error保存照片及证据并进入核查，不调用服务器OCR或无文字的AI。
- 图片过大413，图片／OCR格式、摘要、尺寸或框不匹配422；来源被部署禁用409，detail含稳定code与可读message；APK错误层须支持FastAPI detail字符串、对象和验证数组。

对client成功接收，ScanSession.ocr存以上规范化形状。历史服务器结果可能没有source/model_version/坐标，不回填、不假造置信度；读取缺source的历史结果按server处理。

### 3.4 现有响应与重试

recognize、history、confirm、retry仍使用public_scan的结构：id/request_id/status、label/component/ocr/verification、project_id/project_name、part_id/quantity、image_url、placement、时间和用户名。新增信息位于ocr中，不删除或重命名旧字段。

`POST /api/scan/{id}/retry` 保持无请求体，client任务只重用已保存ocr执行目录／AI核验，绝不重新识别图像。用户主动重新拍摄或本地重识别需新草稿；同版本同照片的首份缓存保持不变，最终采用结果以服务器响应为准。

`/confirm` 的目录身份／自定义元件、quantity、note、new_package保持原样。客户端OCR不是入仓动作，仓储photo和placement仍使用既有接口。

## 4. 数据与缓存设计

无需新表或迁移：ScanSession.ocr保存source/engine/model_version/image摘要，ScanOCRResult.result保存同一结果，原字段和业务身份不变。

- 保留现有服务器 `cache_identity(image)` 的版本环境变量和hash算法，避免旧缓存失效后重复调用OCR。
- 新 `client_cache_identity(result)` 对JSON数组 `["client", engine, model_version, image_sha256]` 使用确定性的JSON序列化（UTF-8、无额外空格）再SHA-256；不能直接拼有歧义的分隔字符串。
- client结果在APK已经推理完成；客户端缓存直接原子插入status=complete的尝试记录，result.status可以是incomplete/error。不建立“等服务器OCR”的processing状态。
- 唯一cache_key处理并发；首份结果为该图像／来源／模型版本的稳定证据。之后同键复用原结果，不覆盖历史文字，APK显示返回的ocr而非假设新提交结果已采用。
- 不同client模型版本、不同图片和server来源各自独立。缓存操作不持有AI网络调用期间的业务写事务。
- 先校验图片／OCR，再保存扫描图片及会话。client结果在会话创建时就保存，避免AI失败使任务丢失OCR后落回服务器。
- request_id、二维码／图片fingerprint、claim_key、project_token及import_package的现有幂等机制继续使用；缓存复用不等于允许再次计数。
- 保存不可用client结果也要保留source="client"，使retry能判定不能进入服务器OCR。历史server任务已保存文字可在client_only继续文字核验；缺失文字则返回明确禁用／需核查状态。

## 5. 文件与接口责任

| 文件 | 责任 |
|---|---|
| 新 app/services/ocr_mode_service.py | OCRMode、有效模式、来源许可、能力响应 |
| 新 app/services/client_ocr_service.py | ClientOCRResult／Line／Image严格类型、图片绑定和结果规范化 |
| 新 app/api/client_api_routes.py | GET capabilities；main.py挂载/api/client |
| app/api/scan_api_routes.py | multipart新字段、长度边界，委托service |
| app/services/scan_ocr_cache.py | 客户端cache key与store_client_once；原服务器recognize_once保留 |
| app/services/scan_import_service.py | 注入结果、来源选择、核验／retry，保留二维码与入库路径 |
| app/api/ocr_api_routes.py | client_only禁止服务器独立识别转发 |
| app/core/config.py、run_windows.py、run_linux.py | SCAN_OCR_MODE、--ocr-mode与启动策略 |
| tests/test_client_ocr_contract.py、test_client_ocr_scan.py、test_ocr_modes.py、test_ocr_launcher_modes.py | 模拟依赖测试，不加载真实模型 |
| paddleocr_vl/API.md、README.md | 双模式部署、共享payload和故障处理 |

固定内部接口：

- `get_ocr_mode() -> OCRMode`；`require_ocr_source(mode, source) -> None` 禁用时抛409；启动非法配置为配置异常。
- `parse_client_ocr(raw_json: str, image_bytes: bytes) -> dict`；先限制JSON大小与图像大小，再严格校验并返回规范化结果。
- `client_cache_identity(result: dict) -> tuple[str, str]` 返回cache_key/image摘要；`store_client_once(db, result: dict) -> dict`返回最终保存证据。
- 保留 `recognize(db, raw, image, project_id, request_id, lang="zh", qr_texts=None)` 的既有位置参数，新增仅关键字参数 `ocr_source="server", ocr_result=None, project_token=None`。
- `verify_scan` 不让client任务调用recognize_once；`retry_scan` 从保存的ocr.source判来源。读取历史无source结果以server处理。
- source许可校验只在确需OCR的非二维码新任务执行；图片／请求基本限制与旧幂等判断维持合理顺序。

## 6. 分阶段实施清单

- [B0：固定基线与兼容测试](stage-b0-baseline-and-compatibility.md)
- [B1：模式、来源与能力接口](stage-b1-ocr-modes-and-capabilities.md)
- [B2：客户端OCR校验、绑定与缓存](stage-b2-client-ocr-validation-and-cache.md)
- [B3：服务器核验、AI、重试与幂等](stage-b3-ai-verification-retry-and-idempotency.md)
- [B4：部署、启动器与跨端验收](stage-b4-deployment-and-cross-client-validation.md)

## 7. 测试命令与验收矩阵

激活当前平台的PartShelf虚拟环境后运行，全部写测试使用既有临时数据库夹具，不连接真实库存进行破坏性验证。当前工作区的.venv是Linux布局（bin/python），不是Windows的Scripts/python.exe；Linux/WSL复用它，Windows需要独立可用的环境（例如.venv-win），不得覆盖现有Linux环境。

```text
python -m pytest tests/test_ocr_modes.py tests/test_client_ocr_contract.py tests/test_client_ocr_scan.py tests/test_ocr_launcher_modes.py -q
python -m pytest tests/test_scan_import.py tests/test_scan_pipeline.py tests/test_scan_ai_contracts.py tests/test_scan_warehouse_integration.py tests/test_legacy_ocr_disabled.py -q
```

实现后的完整测试在临时业务数据库环境执行并记录基线问题；不要使用生产项目作导入回归。

| 情况 | 预期 |
|---|---|
| hybrid旧网页，无新字段 | 服务器OCR一次，既有响应 |
| hybrid APK，合法client OCR | 服务器OCR零次，服务器AI按既有策略 |
| client_only关闭8010/8083 | APK仍可匹配／核查／入库，AI保留 |
| server_only client非QR | 409 client_ocr_disabled |
| client_only server非QR或独立/v1/ocr | 409 server_ocr_disabled |
| 任意模式有效嘉立创QR | 原目录／数量路径，零OCR零AI |
| client结果畸形／摘要尺寸错配 | 422，不入库，不服务器OCR |
| client JSON／图片超限 | 413，不推理 |
| complete但空文字 | needs_review/ocr_empty |
| incomplete/error | 保留照片及结果，人工核查 |
| AI失败／候选冲突／数量缺失 | 既有核查，不默认数量、不换OCR |
| retry client任务 | 保存结果复用，服务器OCR零次 |
| 历史结果无source | 保持可读；已有证据可用于AI |
| 同图同源同版本再次上传 | 首缓存复用；入库仍受扫描幂等控制 |
| 同图client/server或不同版本 | 缓存相互隔离 |
| 重复recognize/confirm | 不重复增加数量或写项目历史 |
| 同标签另一个包装 | 必须new_package显式人工确认 |
| 图片读取与仓储放置 | 原图可读取、必需照片BLOB正常 |
| Android两个测试入口 | 本地运行，业务AI不改为测试Qwen |

## 8. 交付与兼容检查

- [ ] OCR模式、能力JSON、multipart和客户端result示例在两篇计划和API文档中一致。
- [ ] 不改变公开扫描响应主体；新增元数据置于ocr，所有旧字段保留。
- [ ] 不增加业务表；新JSON字段和client缓存键不污染旧记录，旧server cache_identity完全兼容。
- [ ] 覆盖request_id、claim_key和项目身份快照；已有参数冲突／确认与QR规则无回退。
- [ ] 日志记录scan_id、source、engine/model_version、缓存复用和AI阶段，避免将照片／完整OCR文本无条件输出到日志。
- [ ] Android阶段9在全局与快捷搜索后实施，且B1/B2/B3已完成；B4为最终部署验收。
- [ ] 交付包含实际测试结果、两平台启动示例、client_only无OCR进程的联调记录、旧网页hybrid回归记录。
