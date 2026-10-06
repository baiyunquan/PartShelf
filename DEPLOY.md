# PartShelf 部署指南

本文面向在 Linux 服务器上部署 PartShelf 的维护人员。仓库目前没有 Dockerfile、Compose 文件或正式安装器；以下采用 Python 虚拟环境运行 Uvicorn，并可选用 systemd 和 Nginx 管理服务及 HTTPS。

## 1. 部署前准备

- Linux 服务器和 Python 3.10 或更高版本。
- Git、Python venv/pip；使用 MySQL 时还需要可连接的 MySQL 服务和已创建的数据库。
- 足够的磁盘空间。业务数据库和四个参考元件库都需要持久化备份；JLCParts 数据库文件可能较大。
- 若要查询外部元件目录，请准备相应的本地参考库文件，见第 4 节。

## 2. 获取代码并安装依赖

以下示例将项目放在 `/opt/partshelf`，请根据实际路径调整：

将下面示例中的 Git 地址替换成实际 PartShelf 仓库地址。

```bash
sudo mkdir -p /opt/partshelf
sudo chown "$USER":"$USER" /opt/partshelf
git clone https://git.example.com/your-org/PartShelf.git /opt/partshelf
cd /opt/partshelf
git submodule update --init vendor/zxing-wasm

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

应用不需要安装 `requirements-dev.txt`；只有运行测试时才需要安装该文件中的依赖。

生产运行建议使用独立系统账号，并把业务数据库放在代码目录以外：

```bash
sudo useradd --system --home-dir /var/lib/partshelf --shell /usr/sbin/nologin partshelf
sudo install -d -o partshelf -g partshelf /var/lib/partshelf
```

## 3. 配置业务数据库

应用从项目根目录的 `.env` 文件读取配置。`.env` 已被 Git 忽略，不要提交数据库口令。

### SQLite（默认）

不设置 `DATABASE_URL` 时使用 `sqlite:///./partshelf.db`，数据库文件位于项目目录。生产环境可以将业务数据库放在专用数据目录，避免授予服务账号修改代码目录的权限。

也可以在 `.env` 中明确指定绝对路径：

```dotenv
DATABASE_URL=sqlite:////var/lib/partshelf/partshelf.db
PARTSHELF_TEST_MODE=false
```

### MySQL（可选）

先在 MySQL 中创建数据库和专用账号，再设置 SQLAlchemy URL：

```dotenv
DATABASE_URL=mysql+pymysql://partshelf:your_url_encoded_password@127.0.0.1:3306/partshelf?charset=utf8mb4
PARTSHELF_TEST_MODE=false
```

如果口令包含 `@`、`/`、`#` 等 URL 保留字符，应先进行 URL 编码。确保数据库账号对该数据库具有建表、查询和写入权限。

应用启动时会创建缺少的业务表，并初始化“散件”系统项目和 117 个固定抽屉身份。新增的 `warehouse_drawers` 表用于仓位事务锁及分组元数据，实际占用以 `warehouse_placements` 为准；重复启动不会覆盖已有分组元数据，也不会移动已有仓位或照片。这不是完整的数据库迁移框架，升级前请备份。

仓位确认在 SQLite 中使用写事务锁，在 MySQL 中使用元件和抽屉的行锁，并为该写事务设置 `READ COMMITTED`，让等待抽屉锁后的占用查询读取最新提交的数据（参见 [MySQL 官方事务隔离说明](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)）。照片最大 10 MiB，MySQL 的照片列会兼容升级为 `MEDIUMBLOB`；升级时数据库账号需要修改表结构权限。新增接口：`GET /api/warehouse/parts/{part_id}/suggestion?drawer_type=S|L`、带照片的 multipart `POST /api/warehouse/parts/{part_id}/placement` 和 `DELETE /api/warehouse/parts/{part_id}/placement`。读取推荐不会预留仓位。

可在 `app/warehouse_grouping_config.py` 中维护芯片完整型号到基础型号的明确映射，修改后重启服务。单位解析共用 `app/services/electrical_value_service.py`，仓位分组读取原始元件资料，不依赖搜索别名索引。新增映射前应检查已有抽屉；不同组已经混放的抽屉不会参与推荐。

库存添加预览使用只读 `GET /api/warehouse/suggestion`，参数为 `library_source`、`external_part_id`、`quantity`（默认 1）和 `drawer_type`（默认 `S`）；按库存 ID 推荐接口的抽屉类型也默认 `S`。元件资料必须存在于本地目录，预览不会创建库存、仓位或联网抓取资料，查询失败不会阻止用户只保存库存。

机械件策略为任意两种完整规格混放，按来源和完整元件编号去重；正式确认会在事务锁内重新检查上限。此次调整不改变表结构，不会自动移动旧仓位；超过两种机械规格的旧抽屉会保留，但不会参与新分配。

## 4. 准备参考元件库

应用的四个外部元件参考库以独立 SQLite 文件保存在：

```text
/opt/partshelf/data/libraries/
├── jlcparts.db
├── altium_library.db
├── kicad_symbols.db
└── fasteners.db
```

这些数据库文件被 `.gitignore` 排除，不会通过 `git clone` 下载。部署时从可信的数据构建机复制所需文件，或使用项目的 `scripts/` 转换及导入工具生成。确保服务账号可以读写电子元件库文件及所在目录：数值别名索引会在库内创建派生表和变更记录触发器，动态 LCSC 缓存也需要写入权限。

首次启动时，应用会为缺失的参考库尝试运行对应导入流程。部分导入脚本使用开发机上的默认源数据路径；如果部署机没有对应源数据，初始化会记录错误且对应目录不可用。生产部署建议预先生成并复制上述数据库，不依赖首次启动自动转换。

仓库中的 `data/libraries/` 数据库不应当与业务数据库 `partshelf.db` 混淆：前者是元件检索目录，后者保存本地库存、项目、仓储和历史数据。

### 单位等值搜索索引

准备目录后，可以在启动服务前分批构建 C/R/L 数值别名索引：

```bash
.venv/bin/python scripts/rebuild_numeric_aliases.py --source all
```

可用 `--source jlcparts`、`--source altium` 或 `--source kicad` 只处理已安装的目录，或用 `--library-dir /path/to/libraries` 指定目录。默认每批 2000 条，可用 `--batch-size` 调整。脚本输出扫描数量、别名数量以及未发现可解析 C/R/L 参数的记录数量；指定的目录缺失或构建失败时退出码非零。

应用启动时检查索引；解析规则或人工别名配置更新并重启服务后，会按新版本或配置重建。较大的目录首次构建可能需要等待；建议在服务停止时提前运行脚本。后续参数搜索仅重新解析触发器登记的变更记录，也可以用 `--incremental` 主动刷新。完整重建和增量刷新均使用事务，原始目录参数不被改写。构建失败会写入日志并保留原文字搜索，应修复目录权限或数据库问题后重建索引。

### 独立 OCR 服务与扫码资源

浏览器二维码读取使用固定版本的 `vendor/zxing-wasm` 子模块。`static/js/vendor/zxing-wasm/` 已包含同版本的 JavaScript、WASM 和许可证，正常部署无需 Node.js 或 CDN。需要重新生成时运行：

```bash
.venv/bin/python scripts/prepare_scan_assets.py
```

OCR 不安装到 PartShelf 主环境。独立服务使用 Python 3.11、PaddleOCR 2.9.1 和 PaddlePaddle 2.6.2，可部署到另一台设备。服务源码在 `services/paddleocr_api/`；工作区中同步到 ElectronicQwen 后的安装示例：

```bash
.venv/bin/python scripts/sync_ocr_api.py --destination ../ElectronicQwen
cd ../ElectronicQwen
python3.11 -m venv .venv-ocr
.venv-ocr/bin/python -m pip install -r ocr_api/requirements.txt
.venv-ocr/bin/python -m uvicorn ocr_api.server:app --host 127.0.0.1 --port 8010
```

首次加载会下载 PP-OCRv4 模型。离线模型路径、远程监听、Windows 启动和完整接口说明见 [独立 OCR API 文档](services/paddleocr_api/API.md)。该服务可用独立 systemd 服务管理，工作目录和虚拟环境必须与 PartShelf 分开。

在 PartShelf 的 `.env` 中配置服务根地址：

```dotenv
PADDLEOCR_API_URL=http://127.0.0.1:8010
PADDLEOCR_TIMEOUT_SECONDS=60
```

服务可用状态通过 `GET /health` 检查，OCR 接口为 `POST /v1/ocr`。PartShelf 转发图片，浏览器无需直连 OCR 服务。扫码照片限 JPEG、PNG、WebP，最大 10 MiB、2400 万像素；服务账号需对 `data/scan_uploads/` 有写权限。远程摄像头使用 HTTPS。

升级启动时新增 `scan_sessions` 表及项目稳定标识 `projects.identity_token`，为已有项目补齐标识，保留原业务数据。扫码事务同时保存单包库存、项目元件关联及操作者历史；待核查条目保留原项目快照，项目删除或 ID 被新项目复用时不会误入其他项目。

## 5. 配置用户名记录模式

生产环境建议设置：

```dotenv
PARTSHELF_TEST_MODE=false
```

用户首次打开页面时会在浏览器输入一个非空用户名，该值保存在浏览器 Cookie 中，并用于项目元件历史记录。此功能没有密码、账号校验或身份验证；Cookie 中的用户名不能证明操作者身份，不应将应用视为具有用户鉴权的系统。

因此，应将应用部署在可信内网，或放在已有访问控制的网络入口之后。仅启用 HTTPS 只能保护传输过程，不能验证 Cookie 中的用户名是否真实。

`PARTSHELF_TEST_MODE` 未设置时默认为 `true`，便于测试环境直接调用 API。生产环境设置为 `false` 后，没有非空用户名 Cookie 的项目元件新增、数量调整或移除请求会被拒绝。

## 6. 手动启动与检查

在项目目录中运行生产模式的 Uvicorn 命令（不要用会开启热重载的 `run.py`）：

```bash
cd /opt/partshelf
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

应用默认只监听本机回环地址。验证首页、静态资源和 API 文档：

- 首页：`http://127.0.0.1:8000/`
- API 文档：`http://127.0.0.1:8000/docs`
- 参考库状态：`http://127.0.0.1:8000/api/libraries/status`

生产部署应由反向代理提供 HTTPS，不建议直接将 Uvicorn 端口开放到公网。

## 7. 使用 systemd 常驻运行（可选）

创建专用服务账号，并确保它能读取代码、`.env` 和参考库，同时能写入业务数据库及需要生成的本地数据目录。然后创建 `/etc/systemd/system/partshelf.service`：

```ini
[Unit]
Description=PartShelf application
After=network.target

[Service]
Type=simple
User=partshelf
Group=partshelf
WorkingDirectory=/opt/partshelf
EnvironmentFile=/opt/partshelf/.env
ExecStart=/opt/partshelf/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now partshelf
sudo systemctl status partshelf
sudo journalctl -u partshelf -f
```

首次启动时可重点查看日志中的业务数据库初始化和参考库状态。`/api/libraries/status` 返回的目录可用状态可用于确认参考库是否成功加载。

## 8. Nginx 反向代理示例（可选）

配置 TLS 证书后，将站点流量转发到本机 Uvicorn。以下只展示代理段，域名、证书路径及 HTTP 到 HTTPS 跳转按服务器实际配置补齐：

```nginx
server {
    listen 443 ssl;
    server_name partshelf.example.com;

    # 配置 ssl_certificate 和 ssl_certificate_key
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

上传限制应结合实际 BOM 文件大小进行调整。浏览器在 HTTPS 页面会为用户名 Cookie 设置 `Secure` 属性。

## 9. 备份、更新与恢复

至少备份以下内容：

- SQLite 部署中的 `partshelf.db`，或 MySQL 中对应的业务数据库。
- `data/libraries/` 下四个参考元件库。
- `.env`（单独安全保存，不要公开其中的密码）。
- 仓储元件照片保存在业务数据库的 `warehouse_placements` 表中，随业务数据库一并备份。
- 仓储分组与固定抽屉身份保存在同一业务数据库的 `warehouse_drawers` 表中，也需要备份。
- 扫码凭证和核验结果保存在业务数据库的 `scan_sessions` 表中；原图位于 `data/scan_uploads/`，应与数据库一起备份和恢复。

更新前先备份数据库与本地数据；更新后安装依赖、重启服务并检查首页、参考库状态和关键业务流程。SQLite 在线备份应使用 SQLite 备份工具或停写后复制，避免只复制正在使用的数据库主文件而遗漏 WAL 数据。

## 故障排查

- **服务启动失败**：检查 `journalctl -u partshelf -e`、Python 依赖、`.env` 格式以及 `DATABASE_URL` 可达性。
- **首页正常但参考目录为空**：访问 `/api/libraries/status`；确认文件名、文件权限和 SQLite 文件完整性。缺少参考源数据时，自动导入可能无法完成。
- **数据库不可写**：确认服务账号对 `partshelf.db` 所在目录有写权限；SQLite 创建数据库时需要目录可写。
- **BOM 上传失败**：页面接受 CSV、XLSX 和 XLS 扩展名，但解析器使用 `openpyxl` 读取 Excel；建议将旧版 XLS 另存为 XLSX，CSV 请使用 UTF-8 或常见中文编码。
- **用户名反复弹窗或历史记录无操作者**：检查浏览器是否允许 Cookie 和 JavaScript；确认 `PARTSHELF_TEST_MODE=false` 已对服务进程生效，并重新访问页面填写非空用户名。
- **扫码均进入人工核查**：检查独立 OCR 服务 `/health`、模型文件和 PartShelf 的 `PADDLEOCR_API_URL`；查看核验字段中的缺失或冲突原因。嘉立创远程查询与缓存失败也会阻止自动入库。
- **无法启动摄像头**：检查摄像头权限和 HTTPS；本机 `localhost` 可使用摄像头，普通远程 HTTP 请使用照片上传。
