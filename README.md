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
- [API 文档](http://127.0.0.1:8000/docs)（启动应用后访问 / available after startup）
- 许可证 / License: [MIT](LICENSE)

## 简体中文

### 功能

- **库存管理**：记录元件来源、编号、数量、存储位置和备注；从元件库快速加入库存。
- **元件参考库**：查询 JLCParts、Altium、KiCad 和紧固件/机械标准件目录。
- **项目与 BOM**：创建项目、维护项目用量，上传 CSV 或 Excel BOM，预览元件匹配结果并导入新项目或已有项目。
- **采购缺料**：按项目或汇总视图查看需求量、库存量和缺料数量。
- **仓储管理**：选择小/大抽屉，自动推荐兼容仓位，上传实物照片并确认入库；支持移出和打印标签。C/R/L 按单位换算后的主值混放，芯片按明确型号映射混放，机械件按同类混放。
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
│   └── libraries/      # 本地参考元件库数据库（需单独提供，不纳入 Git）
├── scripts/            # 数据转换、导入、数值别名索引和列表列宽辅助脚本
├── static/
│   ├── css/            # 页面样式
│   ├── js/             # 页面交互脚本
│   └── images/         # 本地图片资源
├── templates/          # Jinja2 页面模板
├── tests/              # Python 与 JavaScript 测试
├── Resources/          # README 截图
├── run.py              # 本地开发启动脚本
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
- 元件参考库文件位于 `data/libraries/`：`jlcparts.db`、`altium_library.db`、`kicad_symbols.db`、`fasteners.db`。这些大文件被 Git 忽略，不随源码仓库分发。启动时应用会尝试初始化缺失的参考库；相应源数据不齐时，部分元件库可能不可用。
- 首次访问时，浏览器会要求输入非空用户名。该用户名只用于协作记录，不是账号或身份验证。

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
- **Component catalogs**: Search JLCParts, Altium, KiCad, and fastener/mechanical standards.
- **Projects and BOMs**: Create projects, maintain required quantities, upload CSV or Excel BOMs, review matching results, and import into a new or existing project.
- **Procurement**: Review required, available, and shortage quantities per project or across projects.
- **Warehouse management**: Choose small or large drawers, receive compatible suggestions, upload a photo and confirm physical placement; remove placements and print labels. C/R/L groups use equivalent main values, chips use explicit model mappings, and mechanical parts share drawers within their family.
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
├── scripts/            # Catalog conversion, import, numeric aliases, and list-width tools
├── static/css/         # Page stylesheets
├── static/js/          # Page scripts
├── templates/          # Jinja2 page templates
├── tests/              # Python and JavaScript tests
├── Resources/          # README screenshots
├── run.py              # Local development launcher
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
- Reference catalogs live under `data/libraries/`: `jlcparts.db`, `altium_library.db`, `kicad_symbols.db`, and `fasteners.db`. These large files are Git-ignored and are not distributed with the source. On startup, the application attempts to initialize missing catalogs; some catalogs may remain unavailable if their source data is not present.
- On first visit, the browser prompts for a non-empty username. It is used for activity attribution and is not an account or authentication mechanism.

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
