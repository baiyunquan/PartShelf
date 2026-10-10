# PartShelf

**电子元件与机械标准件库存管理系统 / Electronics and Mechanical Parts Inventory Manager**

[简体中文](#简体中文) | [English](#english)

PartShelf 是基于 FastAPI 的本地部署 Web 应用，用于维护电子元件和机械标准件库存、项目 BOM、采购缺料、仓储位置及协作历史。系统通过外部元件库引用元件资料，并在本地记录库存和项目关联。

PartShelf is a self-hosted web application built with FastAPI. It manages electronic and mechanical component inventory, project BOMs, procurement shortages, warehouse locations, and collaboration history. Component details are referenced from independent catalogs while inventory and project associations are stored locally.

![PartShelf inventory](Resources/Inventory.PNG)

![PartShelf home](Resources/home.PNG)

![PartShelf component details](Resources/Details.PNG)

![PartShelf API documentation](Resources/swagger.JPG)

## 文档 / Documentation

- [部署指南（中文）](DEPLOY.md)
- [使用指南（中文）](USAGE.md)
- [独立 OCR 服务 API 与部署说明（中文）](paddleocr_vl/API.md)
- [扫码修复与样本复验记录 / Scan repair and sample verification](docs/scan-import-followup.md)
- [API 文档](http://127.0.0.1:8000/docs)（启动应用后访问 / available after startup）
- 许可证 / License: [MIT](LICENSE)

## 简体中文

### 功能

- **库存管理**：记录元件来源、编号、数量、存储位置和备注；从元件库快速加入库存。
- **扫码入库**：嘉立创二维码按 C 编号和二维码数量直接入库并加入所选项目，不调用 OCR 或 AI。其他照片仅使用一次 llama.cpp PaddleOCR-VL，识别结果保存供搜索、重试和核查复用；完整型号、封装、数量等证据充分时自动入库，冲突或缺失时人工核查。项目选择持续保留，缺失目录远程拉取并缓存，重复包装不重复入库。
- **元件参考库**：查询 JLCParts、Altium、KiCad 和紧固件/机械标准件目录。
- **项目与 BOM**：创建项目、维护项目用量，上传 CSV 或 Excel BOM，预览元件匹配结果并导入新项目或已有项目。
- **采购缺料**：按项目或汇总视图查看需求量、库存量和缺料数量。
- **仓储管理**：默认推荐小抽屉，也可切换大抽屉；库存单个添加时预览推荐，保存后上传照片并确认入库。支持移出和打印标签，扫描抽屉标签自动定位并打开详情。C/R/L 按单位换算后的主值混放，芯片按明确型号映射混放，机械件允许任意两种完整规格混放。
- **搜索与列表操作**：全局搜索支持 C/R/L 单位等值及组合搜索（如 `电容 2700pf 0603`）；等值结果优先，原文字模糊结果保留；点击表头在当前页面对列表排序；宽表格可横向滚动。
- **协作历史**：记录项目元件的新增、数量变更和移除，可按成员或元件筛选。
- **中英文界面**：界面支持简体中文和英语。

### 技术栈

- Python 3.10+
- FastAPI、Uvicorn、SQLAlchemy、Pydantic
- Jinja2、Bootstrap、原生 JavaScript
- SQLite 默认作为本地业务数据库；也可通过 SQLAlchemy URL 配置 MySQL。
- 四个参考元件库使用独立 SQLite 文件。

### 项目结构

```text
PartShelf/
├── app/
│   ├── api/            # 页面路由及 JSON API
│   ├── crud/           # 数据访问层
│   ├── i18n/           # 界面词条、分类翻译和别名数据
│   ├── models/         # SQLAlchemy 数据模型
│   ├── schemas/        # API 请求和响应结构
│   ├── services/       # BOM、搜索、元件库、库存、项目和仓库业务逻辑
│   ├── main.py         # FastAPI 应用入口及启动初始化
│   ├── warehouse_config.py # 柜体及抽屉几何配置
│   ├── warehouse_grouping_config.py # 芯片基础型号的明确映射
│   └── user_identity.py  # 浏览器用户名 Cookie 处理
├── db/                 # 数据库连接、初始化和维护逻辑
├── data/
│   ├── libraries/      # 本地参考元件库数据库（需单独提供，不纳入 Git）
│   └── scan_uploads/   # 扫码原图与待核查照片（运行时生成，不纳入 Git）
├── scripts/            # 数据转换、导入、数值别名索引和列表列宽辅助脚本
├── paddleocr_vl/       # llama.cpp OCR HTTP 适配层及 API 文档
├── services/paddleocr_api/ # 已停用的旧 PP-OCR 源码，仅供历史参考
├── vendor/zxing-wasm/  # 固定版本的 Sec-ant/zxing-wasm Git 子模块
├── static/
│   ├── css/            # 页面样式
│   ├── js/             # 页面交互脚本
│   └── images/         # 本地图片资源
├── templates/          # Jinja2 页面模板
├── tests/              # Python 与 JavaScript 测试
├── Resources/          # README 截图
├── run.py              # 本地 Web 开发启动脚本
├── run_linux.py        # Linux 全栈启动器
├── run_windows.py      # Windows 全栈启动器
├── requirements.txt    # 运行依赖
├── requirements-dev.txt # 测试依赖
├── DEPLOY.md           # 中文部署说明
└── USAGE.md            # 中文使用说明
```

### 快速启动

需要 Python 3.10 或更高版本。以下示例在仓库的 `PartShelf` 目录中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

然后打开 <http://127.0.0.1:8000>。Windows PowerShell 激活虚拟环境的命令为 `.venv\Scripts\Activate.ps1`。

`run.py` 用于本地开发，会启用自动重载并只监听回环地址。部署到服务器时请参考 [DEPLOY.md](DEPLOY.md)，不要把开发服务器直接暴露到公网。

### 配置与数据

- `DATABASE_URL` 设置本地业务数据库；默认值为 `sqlite:///./partshelf.db`，相对路径以项目目录为基准。MySQL 示例见部署文档。
- `PARTSHELF_TEST_MODE` 默认是 `true`。设为 `false` 后，项目元件修改需要非空用户名 Cookie，以便历史记录归属到对应成员。用户名 Cookie 不是身份验证机制。
- `PADDLEOCR_API_URL` 是独立 OCR 服务的根地址，默认 `http://127.0.0.1:8010`；`PADDLEOCR_TIMEOUT_SECONDS` 默认 `30`。扫码照片最大 10 MiB、2400 万像素，支持 JPEG、PNG、WebP。摄像头远程访问需要 HTTPS，照片上传也可使用 HTTP。
- 元件参考库文件位于 `data/libraries/`：`jlcparts.db`、`altium_library.db`、`kicad_symbols.db`、`fasteners.db`。这些大文件被 Git 忽略，不随源码仓库分发。启动时应用会尝试初始化缺失的参考库；相应源数据不齐时，部分元件库可能不可用。
- 首次访问时，浏览器会要求输入非空用户名。该用户名只用于协作记录，不是账号或身份验证。

### 扫码与独立 OCR 服务

扫码页面位于 `/scan-import`，也可从导航菜单或库存页面进入。二维码运行资源已保存在 `static/js/vendor/zxing-wasm/`，浏览器运行时不依赖 CDN。获取子模块源码和重新生成资源：

```bash
git submodule update --init vendor/zxing-wasm
python scripts/prepare_scan_assets.py
```

OCR 使用 llama.cpp 模型后端（8083）和 PartShelf 主环境中的 HTTP 适配层（8010），可部署到另一台设备。旧 PP-OCRv4/PaddlePaddle 默认推理已停用，无回退路径。部署与 HTTP 契约见 [OCR API 文档](paddleocr_vl/API.md)。

### AI 智能匹配与 llama.cpp 服务

扫码入库（`/scan-import`）与 BOM 匹配（`/bom-import`）全面支持两阶段大模型交互式检索机制：
- **Stage 1 (Extractor)**：从标签 OCR 或 BOM 原始文本中抽取标准化 MPN、品牌、封装与原文中明确出现的电气参数；JSON Schema 约束输出并检查是否完整结束。
- **Stage 2 (Reranker)**：基于本地元器件库（Altium / JLCParts）候选集合，执行结构化技术裁决（`exact_match`、`ambiguous`、`no_match`），完整保留型号后缀，输出简短理由；普通照片的冲突仍需人工核查。嘉立创二维码绕过这两个阶段。

两阶段预算为 512/1200 tokens，严格检查类型、完成状态、下标及裁决一致性。截断最多重试一次相同文字，不再次 OCR；阶段错误和原文证据保存在扫描核验结果中。型号内部空格可合并；长 C/R/L 型号开头的一处字形误读只有在品牌、封装、等价标值及唯一完整目录记录共同支持时才纠正，后缀不改。跨库同型号的品牌/规格冲突分别保留，候选截短时不自动入库。离线审计及只用保存结果的隔离评估见 [OCR API 文档](paddleocr_vl/API.md#4-离线审计与样本复验)。

大模型后端采用本地 `llama.cpp` 原生服务（OpenAI 兼容 `/v1/chat/completions` 接口），默认使用全精度未量化 BF16 模型：
- **端口 8081**：Stage 1 Extractor (`ElectronicQwen-Extractor-v1-BF16.gguf`)
- **端口 8082**：Stage 2 Reranker (`ElectronicQwen-Reranker-v1-BF16.gguf`)

Linux/Windows 全栈启动（llama.cpp OCR、BF16 双搜索后端及 Web 服务）：
```bash
# OCR 模型 8083、OCR 适配层 8010、提取 8081、重排 8082、Web 8000
python run_windows.py
# Linux 使用相同服务配置
python run_linux.py

# 仅拉起 AI/OCR 模型后端服务（后台运行）
python run_windows.py --no-web

# 查看所有服务健康状态
python run_windows.py --status

# 优雅停止所有后端服务
python run_windows.py --stop
```

独立服务管理与运维：
```bash
# 启动 Extractor 与 Reranker 双服务（后台常驻）
python scripts/manage_llama_servers.py start
# 或直接双击 Windows 批处理脚本：
scripts/start_llama_servers.bat

# 查看服务运行状态与模型加载信息
python scripts/manage_llama_servers.py status

# 执行全链路连通性与实测推理核验
python scripts/verify_live_system.py

# 停止服务
python scripts/manage_llama_servers.py stop
# 或使用 Windows 批处理：
scripts/stop_llama_servers.bat
```

### 开发与验证

电容、电阻、电感的派生别名索引首次启动时自动构建；目录数据变更后，参数搜索前按变更记录更新。也可以提前生成或完整重建，减少首次启动等待：

```bash
python scripts/rebuild_numeric_aliases.py --source all
python scripts/rebuild_numeric_aliases.py --source jlcparts --incremental
```

脚本支持 `--library-dir` 和 `--batch-size`，输出扫描数、别名数及未发现可解析 C/R/L 参数的记录数。只更新派生表，保留原目录参数。首次构建较大的目录需要时间；数据库及所在目录需要可写，部署说明见 [DEPLOY.md](DEPLOY.md)。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

列表列宽辅助脚本可以先生成只读报告，再将估算宽度写入 CSS：

```bash
python scripts/generate_list_widths.py --report
python scripts/generate_list_widths.py --write
```

## English

### Features

- **Inventory management**: Track catalog source, part identifier, quantity, storage location, and notes; add catalog parts to inventory.
- **Scan import**: Local ZXing WASM reads JLC packaging QR codes. A valid C number and QR quantity import directly into inventory and the selected project, with zero OCR or AI calls. Other photos use one llama.cpp PaddleOCR-VL pass, persisted for matching, retries, and review. Complete label evidence can import automatically; conflicts and missing fields require review. Project selection persists, missing catalog entries are fetched and cached, and repeated bags do not add stock twice.
- **Component catalogs**: Search JLCParts, Altium, KiCad, and fastener/mechanical standards.
- **Projects and BOMs**: Create projects, maintain required quantities, upload CSV or Excel BOMs, review matching results, and import into a new or existing project.
- **Procurement**: Review required, available, and shortage quantities per project or across projects.
- **Warehouse management**: Small drawers are suggested by default, with a large-drawer option. Preview a location when adding one inventory part, then save inventory and continue to photo confirmation. Remove placements, print labels, and scan a drawer label to open its details. C/R/L groups use equivalent main values, chips use explicit model mappings, and each mechanical drawer accepts up to two complete specifications from any mechanical family.
- **Search and list controls**: Search across the application with C/R/L unit equivalence and combined keywords; equivalent parameters precede retained text matches. Click table headers to sort the current list; wide tables can scroll horizontally.
- **Activity history**: Track project component additions, quantity changes, and removals, with filters for members and components.
- **Bilingual interface**: The web interface supports Simplified Chinese and English.

### Technology

- Python 3.10+
- FastAPI, Uvicorn, SQLAlchemy, and Pydantic
- Jinja2, Bootstrap, and vanilla JavaScript
- SQLite is the default application database. MySQL can be configured with a SQLAlchemy URL.
- The four reference catalogs are stored in separate SQLite files.

### Project layout

```text
PartShelf/
├── app/
│   ├── api/            # Page routes and JSON APIs
│   ├── crud/           # Data access layer
│   ├── i18n/           # UI translations, category translations, and aliases
│   ├── models/         # SQLAlchemy models
│   ├── schemas/        # API request and response schemas
│   ├── services/       # BOM, search, catalog, inventory, project, and warehouse logic
│   ├── main.py         # FastAPI entry point and startup initialization
│   ├── warehouse_config.py # Cabinet and drawer geometry
│   ├── warehouse_grouping_config.py # Explicit chip base-model mappings
│   └── user_identity.py  # Browser username cookie handling
├── db/                 # Database connection, initialization, and maintenance
├── data/libraries/     # Local reference catalog databases (provided separately)
├── data/scan_uploads/  # Original scan photographs (generated at runtime, Git-ignored)
├── scripts/            # Catalog conversion, import, numeric aliases, and list-width tools
├── paddleocr_vl/       # llama.cpp OCR HTTP adapter and API guide
├── services/paddleocr_api/ # Disabled legacy PP-OCR source, retained for reference
├── vendor/zxing-wasm/  # Pinned Sec-ant/zxing-wasm Git submodule
├── static/css/         # Page stylesheets
├── static/js/          # Page scripts
├── templates/          # Jinja2 page templates
├── tests/              # Python and JavaScript tests
├── Resources/          # README screenshots
├── run.py              # Local Web development launcher
├── run_linux.py        # Linux full-stack launcher
├── run_windows.py      # Windows full-stack launcher
├── requirements.txt    # Runtime dependencies
├── requirements-dev.txt # Test dependencies
├── DEPLOY.md           # Chinese deployment guide
└── USAGE.md            # Chinese user guide
```

### Quick start

Python 3.10 or newer is required. Run these commands from the `PartShelf` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:8000>. In Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1`.

`run.py` is for local development: it enables reload and binds to loopback. For server deployment, see [DEPLOY.md](DEPLOY.md); do not expose the development server directly to the public Internet.

### Configuration and data

- `DATABASE_URL` configures the application database. The default is `sqlite:///./partshelf.db`, resolved relative to the project directory. See the deployment guide for a MySQL example.
- `PARTSHELF_TEST_MODE` defaults to `true`. Set it to `false` to require a non-empty username cookie for project component changes and attribute history entries to a member. The username cookie is not an authentication mechanism.
- `PADDLEOCR_API_URL` points to the independent OCR service root, defaulting to `http://127.0.0.1:8010`; `PADDLEOCR_TIMEOUT_SECONDS` defaults to `30`. Scan photographs accept JPEG, PNG, and WebP up to 10 MiB and 24 million pixels. Remote camera access requires HTTPS; photograph uploads also work over HTTP.
- Reference catalogs live under `data/libraries/`: `jlcparts.db`, `altium_library.db`, `kicad_symbols.db`, and `fasteners.db`. These large files are Git-ignored and are not distributed with the source. On startup, the application attempts to initialize missing catalogs; some catalogs may remain unavailable if their source data is not present.
- On first visit, the browser prompts for a non-empty username. It is used for activity attribution and is not an account or authentication mechanism.

### Scanning and the independent OCR service

Open `/scan-import` through the navigation menu or inventory page. Runtime QR assets are committed under `static/js/vendor/zxing-wasm/` and require no CDN. To obtain the upstream source and regenerate assets:

```bash
git submodule update --init vendor/zxing-wasm
python scripts/prepare_scan_assets.py
```

OCR runs through llama.cpp on port 8083 and the PartShelf HTTP adapter on port 8010, and can be hosted on another device. The legacy PP-OCRv4/PaddlePaddle runtime is disabled and has no fallback path. Its setup commands and HTTP contract are documented in the [OCR API guide](paddleocr_vl/API.md).

Text extraction and reranking use strict JSON schemas with budgets of 512 and 1200 tokens. Responses are checked for completion, field types, candidate indices, and consistent decisions. A truncated text completion may retry once using the same saved OCR; images are never scanned again. Evidence and stage errors remain available for review. Spaces inside complete models may be removed. One glyph error in the initial series of a long C/R/L model can be corrected only with matching brand, explicit package, equivalent value, and a unique complete catalog identity; suffixes remain unchanged. Conflicting brands/specifications are retained separately, and truncated candidate pools cannot auto-import. Read-only identity audits and isolated evaluations using saved llama.cpp OCR are documented in the [OCR API guide](paddleocr_vl/API.md#4-离线审计与样本复验).

### Development and verification

Derived capacitance, resistance, and inductance aliases are built at startup and refreshed from changed records before parameter searches. Rebuild them ahead of startup when preparing a large catalog:

```bash
python scripts/rebuild_numeric_aliases.py --source all
python scripts/rebuild_numeric_aliases.py --source jlcparts --incremental
```

The helper accepts `--library-dir` and `--batch-size`, reporting scanned records, aliases, and records without parseable C/R/L values. It writes derived tables while preserving original parameters. Catalog files and their directory must be writable. Search supports equivalent units (`2700pF = 2.7nF`), resistor shorthand (`4k7 = 4.7kΩ`), and combined keywords; equivalent results precede retained text matches. Note that `2700000pF = 2.7uF`, and `m` and `M` represent different prefixes. Bare numbers and model fragments are not converted.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The list-width helper can produce a read-only report and apply estimated CSS widths:

```bash
python scripts/generate_list_widths.py --report
python scripts/generate_list_widths.py --write
```
