"""Split migration plans into stage files and append verified source references.

Run: py -3 scripts/split_migration_plans.py
Check without writing: py -3 scripts/split_migration_plans.py --check

The source plans are read only. Existing generated files are replaced
deterministically; unrelated files are never deleted.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys


PLAN_DIR = Path("docs/superpowers/plans")
ANDROID_SOURCE = "2026-10-10-android-frontend-migration.md"
BACKEND_SOURCE = "2026-10-10-client-ocr-backend.md"
ANDROID_FOLDER = "android-frontend-migration"
BACKEND_FOLDER = "client-ocr-backend"
ANDROID_PACKAGE = "app/src/main/java/com/liaic/radiolabrepository/"
DEFAULT_ANDROID_ROOT = Path("C:/Users/liaic/AndroidStudioProjects/RadioLabRepository")
TICK = chr(96)
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass(frozen=True)
class FileReference:
    path: str
    purpose: str
    android: bool = False


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    purpose: str
    kind: str = "existing"
    implementation: str | None = None


@dataclass(frozen=True)
class StageSpec:
    filename: str
    frontend: tuple[FileReference, ...]
    endpoints: tuple[Endpoint, ...]
    note: str = ""


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    text: str


@dataclass(frozen=True)
class ParsedPlan:
    prefix: str
    stage_heading: str
    stages: tuple[Stage, ...]
    suffix: str


def web(*paths: str) -> tuple[FileReference, ...]:
    return tuple(FileReference(path, "现有网页结构、样式或交互") for path in paths)


def android(*paths: str) -> tuple[FileReference, ...]:
    return tuple(
        FileReference(ANDROID_PACKAGE + path, "现有 APK 基础与测试入口", True)
        for path in paths
    )


def api(method: str, path: str, purpose: str) -> Endpoint:
    return Endpoint(method, path, purpose)


CAPABILITIES = Endpoint(
    "GET", "/api/client/capabilities", "OCR 模式、客户端契约及上传限制",
    "planned", "app/api/client_api_routes.py",
)
LIBRARY_STATUS = api("GET", "/api/libraries/status", "旧服务器连接探针、元件库可用状态")
INVENTORY_READ = (
    api("GET", "/api/inventory/get_parts_inventory", "全部库存及 warehouse_status 筛选"),
    api("GET", "/api/inventory/search", "search_key 搜索及仓储状态筛选"),
    api("GET", "/api/inventory/get_part_by_id", "part_id 详情、照片与项目关联"),
)
INVENTORY_WRITE = (
    api("POST", "/api/inventory/add_part_to_inventory", "按来源和编号添加本地库存"),
    api("POST", "/api/inventory/update_quantity", "设置绝对可用量"),
    api("POST", "/api/inventory/update_meta", "修改位置和备注"),
    api("DELETE", "/api/inventory/delete_part", "删除本地元件"),
)
PROJECT_READ = (
    api("GET", "/api/projects/", "项目与散件列表；普通响应不含扫码 identity_token"),
    api("GET", "/api/projects/{project_id}", "项目／散件详情、可用量和需求"),
)
PROJECT_WRITE = (
    api("POST", "/api/projects/api_add", "JSON 创建普通项目"),
    api("PUT", "/api/projects/{project_id}", "修改普通项目"),
    api("DELETE", "/api/projects/{project_id}", "删除普通项目"),
    api("POST", "/api/projects/{project_id}/add_part", "关联元件及需求数量"),
    api("POST", "/api/projects/{project_id}/update_part_quantity", "修改项目需求"),
    api("DELETE", "/api/projects/{project_id}/remove_part/{part_id}", "解除关联"),
)
BOM_API = (
    api("POST", "/api/projects/bom/preview", "multipart file，服务端解析和预览"),
    api("POST", "/api/projects/bom/suggest", "原编号／型号／参数候选"),
    api("POST", "/api/projects/bom/custom_part", "人工自定义元件"),
    api("POST", "/api/projects/bom/import", "确认后创建新批次；当前没有幂等键"),
)
WAREHOUSE_API = (
    api("GET", "/api/warehouse/contents", "配置驱动箱体几何、抽屉内容与未入仓数量"),
    api("GET", "/api/warehouse/suggestion", "目录元件的放置建议"),
    api("GET", "/api/warehouse/parts/{part_id}/suggestion", "本地元件建议；drawer_type=S/L"),
    api("POST", "/api/warehouse/parts/{part_id}/placement", "cabinet_id/drawer_code/photo 放置"),
    api("DELETE", "/api/warehouse/parts/{part_id}/placement", "移除放置"),
    api("GET", "/api/warehouse/parts/{part_id}/photo", "仓储照片 BLOB 读取"),
)
SEARCH_API = (
    api("GET", "/api/search/quick", "navbar 即时预览；q"),
    api("GET", "/api/search/aggregate", "q/tab/page/page_size 分组和分页"),
    api("GET", "/api/libraries/search", "指定来源候选检索"),
)
SCAN_API = (
    api("GET", "/api/scan/projects", "扫码专用项目列表，包含 identity_token"),
    api("POST", "/api/scan/recognize", "照片及二维码；计划增加 client OCR 与 project_token"),
    api("GET", "/api/scan/history", "扫描状态及已保存证据"),
    api("POST", "/api/scan/{scan_id}/confirm", "候选／自定义元件、数量、new_package 确认"),
    api("POST", "/api/scan/{scan_id}/retry", "复用已保存证据；client 不再次 OCR"),
    api("GET", "/api/scan/{scan_id}/image", "扫描原图读取"),
)
OCR_PROXY = (
    api("POST", "/v1/ocr", "PartShelf 服务器 OCR 兼容转发；client_only 计划禁用"),
    api("POST", "/api/ocr/ocr", "PartShelf 服务器 OCR 转发别名"),
)
OCR_EXTERNAL = (
    Endpoint("GET", "/health", "8010 OCR 适配层就绪检查", "external", "paddleocr_vl/server.py"),
    Endpoint("POST", "/v1/ocr", "8010 OCR 适配层识别；client 路径不得调用", "external", "paddleocr_vl/server.py"),
)
AI_EXTERNAL = (
    Endpoint("POST", "/v1/chat/completions", "8081 提取与 8082 重排；保留服务器 AI",
             "external", "app/services/multi_turn_evaluator.py"),
)
LIBRARY_API = {
    "7.1": (
        api("GET", "/api/libraries/jlcparts/categories", "分类／子分类树"),
        api("GET", "/api/libraries/jlcparts", "参数、分类、封装、库类型、有货及分页"),
        api("GET", "/api/libraries/jlcparts/{lcsc}", "精确 C 号详情及动态缓存"),
    ),
    "7.2": (
        api("GET", "/api/libraries/altium/categories", "Altium 分类"),
        api("GET", "/api/libraries/altium/packages", "Altium 封装"),
        api("GET", "/api/libraries/altium", "q/category/package/basic_only 及分页"),
        api("GET", "/api/libraries/altium/{comp_id}", "Altium 原始整数 ID 详情"),
    ),
    "7.3": (
        api("GET", "/api/libraries/kicad/libraries", "符号库分类"),
        api("GET", "/api/libraries/kicad", "q/library 及分页"),
        api("GET", "/api/libraries/kicad/{symbol_id}", "符号详情与原始数据"),
    ),
    "7.4": (
        api("GET", "/api/libraries/fasteners/domains", "机械领域"),
        api("GET", "/api/libraries/fasteners/categories", "机械分类"),
        api("GET", "/api/libraries/fasteners/authorities", "标准体系"),
        api("GET", "/api/libraries/fasteners/metadata", "标准元数据"),
        api("GET", "/api/libraries/fasteners", "q/domain/category/authority 及分页"),
        api("GET", "/api/libraries/fasteners/{standard_code}", "标准参数、长度和装配详情"),
        api("POST", "/api/libraries/fasteners/{standard_code}/specs", "自定义规格"),
        api("GET", "/api/libraries/fasteners/assembly-guide", "装配指导"),
        api("GET", "/api/libraries/fasteners/hole-charts/{chart_type}", "孔径表"),
    ),
}
LIBRARY_FRONTEND = {
    key: web(
        f"templates/libraries_{name}.html",
        f"templates/libraries_{name}_details.html",
        f"static/js/libraries_{name}.js",
        f"static/js/libraries_{name}_details.js",
        f"static/css/libraries_{name}.css",
        "templates/partials/libraries_tabs.html",
        "templates/partials/import_modal.html",
        "static/js/import_to_inventory_modal.js",
    )
    for key, name in (("7.1", "jlcparts"), ("7.2", "altium"), ("7.3", "kicad"), ("7.4", "fasteners"))
}
NAV_FRONTEND = web(
    "templates/partials/navbar.html", "templates/partials/language_switcher.html",
    "static/js/navbar_search.js", "static/js/user_identity.js",
)
SCAN_FRONTEND = web("templates/scan_import.html", "static/js/scan_import.js",
                    "static/js/scan_label.js", "static/css/scan_import.css")
WAREHOUSE_FRONTEND = web(
    "templates/warehouse.html", "static/js/warehouse.js",
    "static/js/warehouse_placement.js", "static/js/warehouse_scan.js",
    "static/css/warehouse.css", "static/js/vendor/qrcode-generator.js",
)
ALL_LIBRARY_ENDPOINTS = tuple(endpoint for group in LIBRARY_API.values() for endpoint in group)
ALL_LIBRARY_FRONTEND = tuple(reference for group in LIBRARY_FRONTEND.values() for reference in group)
READ_ONLY_TEST_NOTE = "两个现有端侧测试入口本身不依赖业务后端；只读接口仅用于连接和基线对照。"

ANDROID_SPECS = {
    "0": StageSpec("stage-00-baseline-and-test-protection.md",
                   android("MainActivity.kt", "ModelManager.kt", "OcrManager.kt", "ui/OcrScreen.kt")
                   + (FileReference("app/build.gradle.kts", "现有 SDK、ABI 与原生库打包", True),
                      FileReference("gradle/libs.versions.toml", "既有构建依赖", True)),
                   (LIBRARY_STATUS,), READ_ONLY_TEST_NOTE),
    "1": StageSpec("stage-01-backend-connection.md", NAV_FRONTEND
                   + (FileReference("app/src/main/AndroidManifest.xml", "网络与相机权限基线", True),),
                   (CAPABILITIES, LIBRARY_STATUS) + INVENTORY_READ[:1]),
    "2": StageSpec("stage-02-ui-shell-sidebar-and-tests.md", NAV_FRONTEND
                   + web("templates/home.html", "static/css/home.css")
                   + android("MainActivity.kt", "ModelManager.kt", "ui/OcrScreen.kt", "ui/theme/Theme.kt"),
                   (CAPABILITIES, LIBRARY_STATUS) + SEARCH_API[:1],
                   "快捷搜索此时仅提供雏形，完整交互在阶段 8；两个测试入口仍离线可用。"),
    "3": StageSpec("stage-03-warehouse.md", WAREHOUSE_FRONTEND, WAREHOUSE_API + INVENTORY_READ,
                   "箱体配置另参考 app/warehouse_config.py；仓储规则参考 app/services/warehouse_service.py。"),
    "4": StageSpec("stage-04-inventory-and-details.md",
                   web("templates/inventory.html", "templates/component_details.html",
                       "static/js/inventory.js", "static/js/inventory_recommendation.js",
                       "static/js/component_details.js", "static/js/component_links.js",
                       "static/css/inventory.css"),
                   INVENTORY_READ + INVENTORY_WRITE + PROJECT_READ + SEARCH_API[2:] + WAREHOUSE_API[:1]),
    "5": StageSpec("stage-05-projects-and-loose-parts.md",
                   web("templates/projects.html", "templates/project_details.html",
                       "static/js/projects.js", "static/js/project_details.js",
                       "static/css/projects.css", "static/css/project_details.css"),
                   PROJECT_READ + PROJECT_WRITE + INVENTORY_READ[:1]),
    "6": StageSpec("stage-06-bom-import.md",
                   web("templates/bom_import.html", "templates/partials/bom_import_helpers.html",
                       "static/js/bom_import.js", "static/css/bom_import.css",
                       "templates/project_details.html", "static/js/project_details.js"),
                   BOM_API + PROJECT_READ,
                   "BOM 当前没有 request_id 幂等接口；结果未知时按本阶段的持久化状态要求人工核查。"),
    "7": StageSpec("stage-07-component-libraries.md", ALL_LIBRARY_FRONTEND,
                   ALL_LIBRARY_ENDPOINTS + INVENTORY_WRITE[:1] + PROJECT_READ,
                   "四个子阶段分别执行；共享文件、导入流程和上限在本文件统一规定。"),
    "8": StageSpec("stage-08-global-and-quick-search.md",
                   web("templates/search.html", "static/js/search.js", "static/css/search.css",
                       "templates/partials/navbar.html", "static/js/navbar_search.js",
                       "static/js/component_links.js", "static/js/import_to_inventory_modal.js"),
                   SEARCH_API + INVENTORY_WRITE[:1],
                   "本阶段完成后才进入阶段 9 扫码入库。"),
    "9": StageSpec("stage-09-scan-import-and-local-ocr.md",
                   SCAN_FRONTEND + WAREHOUSE_FRONTEND
                   + android("OcrManager.kt", "ui/OcrScreen.kt", "ModelManager.kt"),
                   (CAPABILITIES,) + SCAN_API + WAREHOUSE_API + AI_EXTERNAL,
                   "client 所需 OCR 字段和 project_token 为计划扩展；当前 /recognize 还不能按该新契约接收客户端结果。"),
    "10": StageSpec("stage-10-home-procurement-and-history.md",
                    web("templates/home.html", "static/css/home.css",
                        "templates/procurement.html", "static/js/procurement.js", "static/css/procurement.css",
                        "templates/project_history.html", "static/js/project_history.js", "static/css/project_history.css"),
                    (api("GET", "/api/projects/procurement/list", "全局缺口与项目需求"),
                     api("GET", "/api/projects/procurement/project/{project_id}", "项目采购需求"),
                     api("GET", "/api/projects/history", "成员／无归属／元件历史，分页字段 pages")) + PROJECT_READ),
    "11": StageSpec("stage-11-integration-and-apk-delivery.md",
                    NAV_FRONTEND + WAREHOUSE_FRONTEND + SCAN_FRONTEND
                    + web("templates/inventory.html", "templates/projects.html",
                          "templates/bom_import.html", "templates/search.html")
                    + android("MainActivity.kt", "ModelManager.kt", "OcrManager.kt", "ui/OcrScreen.kt"),
                    (CAPABILITIES, LIBRARY_STATUS) + INVENTORY_READ + INVENTORY_WRITE[:2]
                    + WAREHOUSE_API + PROJECT_READ + BOM_API + SEARCH_API + SCAN_API + AI_EXTERNAL),
}
for key, suffix in (("7.1", "jlcparts"), ("7.2", "altium"), ("7.3", "kicad"), ("7.4", "mechanical-standards")):
    ANDROID_SPECS[key] = StageSpec(
        f"stage-07-0{key[-1]}-{suffix}.md", LIBRARY_FRONTEND[key],
        LIBRARY_API[key] + INVENTORY_WRITE[:1] + PROJECT_READ,
        "先阅读父阶段的共享 DTO、Repository、分页上限和统一导入要求。",
    )

BACKEND_SPECS = {
    "B0": StageSpec("stage-b0-baseline-and-compatibility.md", SCAN_FRONTEND
                    + android("OcrManager.kt", "ui/OcrScreen.kt"),
                    SCAN_API + OCR_PROXY + OCR_EXTERNAL,
                    "核对当前网页行为和 APK 本地结果，不恢复旧 PP-OCRv4 部署。"),
    "B1": StageSpec("stage-b1-ocr-modes-and-capabilities.md", SCAN_FRONTEND + NAV_FRONTEND,
                    (CAPABILITIES,) + SCAN_API[:2] + OCR_PROXY),
    "B2": StageSpec("stage-b2-client-ocr-validation-and-cache.md", SCAN_FRONTEND
                    + android("OcrManager.kt", "ui/OcrScreen.kt"),
                    SCAN_API[1:2] + SCAN_API[2:3] + SCAN_API[5:] + OCR_EXTERNAL,
                    "外部 OCR 接口仅用于服务器兼容对照，client 路径必须验证零调用。"),
    "B3": StageSpec("stage-b3-ai-verification-retry-and-idempotency.md",
                    SCAN_FRONTEND + WAREHOUSE_FRONTEND
                    + web("templates/project_history.html", "static/js/project_history.js"),
                    SCAN_API + WAREHOUSE_API + INVENTORY_READ[:1] + AI_EXTERNAL),
    "B4": StageSpec("stage-b4-deployment-and-cross-client-validation.md",
                    SCAN_FRONTEND + android("MainActivity.kt", "ModelManager.kt", "OcrManager.kt", "ui/OcrScreen.kt"),
                    (CAPABILITIES,) + SCAN_API + OCR_PROXY + OCR_EXTERNAL + AI_EXTERNAL,
                    "启动器另参考 run_windows.py、run_linux.py；client_only 跳过 8010/8083，AI 保留。"),
}


def code(value: str) -> str:
    return TICK + value + TICK


def markdown_link(label: str, target: Path, output: Path) -> str:
    if target.drive and target.drive.lower() != output.drive.lower():
        location = target.as_posix()
    else:
        location = Path(os.path.relpath(target, output.parent)).as_posix()
    return f"[{label}](<{location}>)"


def rewrite_plan_links(text: str) -> str:
    return (text.replace(f"]({ANDROID_SOURCE})", f"](../{ANDROID_FOLDER}/README.md)")
                .replace(f"]({BACKEND_SOURCE})", f"](../{BACKEND_FOLDER}/README.md)"))


def heading_positions(text: str) -> list[tuple[int, int, str]]:
    headings = []
    position = 0
    fence = None
    for line in text.splitlines(keepends=True):
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
        elif fence is None:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                headings.append((position, len(match.group(1)), match.group(2)))
        position += len(line)
    if fence is not None:
        raise ValueError("Unclosed Markdown code fence")
    return headings


def parse_plan(path: Path, android_plan: bool) -> ParsedPlan:
    text = path.read_text(encoding="utf-8")
    headings = heading_positions(text)
    pattern = re.compile(r"^阶段\s+(\d+)[：:]") if android_plan else re.compile(r"^(B\d+)[：:]")
    stage_entries = [(start, title, pattern.match(title).group(1))
                     for start, level, title in headings if level == 3 and pattern.match(title)]
    expected = [str(i) for i in range(12)] if android_plan else [f"B{i}" for i in range(5)]
    if [entry[2] for entry in stage_entries] != expected:
        raise ValueError(f"{path.name}: stage headings changed; update the splitter mapping first")
    first = stage_entries[0][0]
    parent_start, _, stage_heading = max(
        (entry for entry in headings if entry[0] < first and entry[1] == 2), key=lambda entry: entry[0]
    )
    parent_end = text.find("\n", parent_start) + 1
    if text[parent_end:first].strip():
        raise ValueError(f"{path.name}: unexpected content before first stage")
    final = min((start for start, level, _ in headings if start > stage_entries[-1][0] and level <= 2),
                default=len(text))
    stages = []
    for index, (start, title, key) in enumerate(stage_entries):
        end = stage_entries[index + 1][0] if index + 1 < len(stage_entries) else final
        stages.append(Stage(key, title, text[start:end].strip()))
    return ParsedPlan(text[:parent_start].rstrip(), stage_heading, tuple(stages), text[final:].strip())


def split_library_children(parent: Stage) -> tuple[Stage, tuple[Stage, ...]]:
    headings = heading_positions(parent.text)
    matches = [(start, title, re.match(r"^(7\.[1-4])\s", title).group(1))
               for start, level, title in headings if level == 4 and re.match(r"^7\.[1-4]\s", title)]
    if [entry[2] for entry in matches] != ["7.1", "7.2", "7.3", "7.4"]:
        raise ValueError("Stage 7 substage headings changed")
    tail_match = re.search(r"^\*\*共享导入[：:]", parent.text, re.M)
    if not tail_match or tail_match.start() < matches[-1][0]:
        raise ValueError("Stage 7 shared import section is missing")
    tail = tail_match.start()
    raw_chunks = []
    children = []
    for index, (start, title, key) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else tail
        raw_chunks.append(parent.text[start:end])
        children.append(Stage(key, f"子阶段 {title}", parent.text[start:end].strip()))
    prefix = parent.text[:matches[0][0]]
    suffix = parent.text[tail:]
    if prefix + "".join(raw_chunks) + suffix != parent.text:
        raise ValueError("Stage 7 content preservation check failed")
    links = "\n".join(f"- [{child.title}]({ANDROID_SPECS[child.key].filename})" for child in children)
    shared_text = prefix.rstrip() + "\n\n## 元件库子阶段\n\n" + links + "\n\n" + suffix
    return Stage(parent.key, parent.title, shared_text), tuple(children)


def file_routes(path: Path) -> dict[tuple[str, str], tuple[Path, int]]:
    routes = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in HTTP_METHODS and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)):
                routes[(decorator.func.attr.upper(), decorator.args[0].value)] = (path, node.lineno)
    return routes


def api_catalog(repo: Path) -> dict[tuple[str, str], tuple[Path, int]]:
    catalog = {}
    tree = ast.parse((repo / "app/main.py").read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router" and node.args):
            continue
        router = node.args[0]
        if not (isinstance(router, ast.Attribute) and isinstance(router.value, ast.Name)):
            continue
        prefix = next((keyword.value.value for keyword in node.keywords
                       if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant)), "")
        implementation = repo / f"app/api/{router.value.id}.py"
        for (method, path), target in file_routes(implementation).items():
            catalog[(method, prefix + path)] = target
    return catalog


def unique(items: tuple) -> tuple:
    return tuple(dict.fromkeys(items))


def reference_footer(spec: StageSpec, output: Path, repo: Path, android_root: Path, catalog: dict) -> str:
    lines = ["## 阶段参考", "", "### 应参考的前端文件", "",
             "| 文件 | 用途 |", "|---|---|"]
    for reference in unique(spec.frontend):
        target = (android_root if reference.android else repo) / reference.path
        if not target.is_file():
            raise FileNotFoundError(f"Missing frontend reference: {target}")
        label = ("APK: " if reference.android else "") + reference.path
        lines.append(f"| {markdown_link(label, target, output)} | {reference.purpose} |")
    lines += ["", "### 应参考的后端接口", "",
              "| 方法与路径 | 状态与用途 | 实现参考 |", "|---|---|---|"]
    for endpoint in unique(spec.endpoints):
        identity = (endpoint.method, endpoint.path)
        if endpoint.kind == "external":
            target = repo / endpoint.implementation
            if not target.is_file():
                raise FileNotFoundError(target)
            if endpoint.implementation == "paddleocr_vl/server.py" and identity not in file_routes(target):
                raise ValueError(f"Unknown adapter endpoint: {identity}")
            status = "外部服务"
        elif identity in catalog:
            target = catalog[identity][0]
            status = "现有接口" if endpoint.kind == "existing" else "已实现原计划接口"
        elif endpoint.kind == "planned":
            target = None
            status = "计划新增，当前未实现"
        else:
            raise ValueError(f"Unknown PartShelf endpoint: {identity}")
        implementation = (markdown_link(str(target.relative_to(repo)).replace(os.sep, "/"), target, output)
                          if target else code(endpoint.implementation + "（计划文件）"))
        lines.append(f"| {code(endpoint.method + ' ' + endpoint.path)} | {status}；{endpoint.purpose} | {implementation} |")
    lines += ["", "新增 client OCR 字段、部署模式和项目 token 以 "
              f"[共享后端契约](../{BACKEND_FOLDER}/README.md) 为准；现有路径不代表新字段已经支持。"]
    if spec.note:
        lines += ["", spec.note]
    return "\n".join(lines)


def render_stage(stage: Stage, spec: StageSpec, output: Path, repo: Path, android_root: Path,
                 catalog: dict, source: Path, previous: str | None, following: str | None,
                 parent: str | None = None) -> str:
    context = [
        f"# {stage.title}", "",
        "> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。",
        "",
        "执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。",
        f"原始完整计划：{markdown_link(source.name, source, output)}。",
    ]
    navigation = []
    if previous:
        navigation.append(f"[上一阶段]({previous})")
    if following:
        navigation.append(f"[下一阶段]({following})")
    if parent:
        navigation.append(f"[父阶段与共享导入]({parent})")
    if navigation:
        context += ["", " · ".join(navigation)]
    # Preserve the body verbatim; only its original heading is replaced.
    body = stage.text.split("\n", 1)[1].strip()
    return ("\n".join(context) + "\n\n" + rewrite_plan_links(body) + "\n\n---\n\n"
            + reference_footer(spec, output, repo, android_root, catalog) + "\n")


def render_readme(parsed: ParsedPlan, source: Path, output: Path,
                  stages: tuple[Stage, ...], specs: dict, children: tuple[Stage, ...],
                  repo: Path) -> str:
    introduction = (
        "> 此目录由 scripts/split_migration_plans.py 程序化拆分。先读本总览，再按阶段文件执行；"
        "各阶段尾部附当前前端文件和后端接口。\n\n"
        f"原始完整计划：{markdown_link(source.name, source, output)}。\n\n"
        "共享约束、架构／协议及验收要求保留在本文件，阶段正文保留在独立文件中。\n\n"
        f"生成工具：{markdown_link('split_migration_plans.py', repo / 'scripts/split_migration_plans.py', output)}。"
        "在 PartShelf 根目录运行下列命令；阶段文件由程序维护，直接编辑会在重新生成时被覆盖。\n\n"
        + TICK * 3 + "text\npy -3 scripts/split_migration_plans.py\n"
        "py -3 scripts/split_migration_plans.py --check\n" + TICK * 3 + "\n\n"
    )
    prefix = rewrite_plan_links(parsed.prefix)
    first, rest = prefix.split("\n", 1)
    prefix = first + "\n\n" + introduction + rest.lstrip()
    index = []
    for stage in stages:
        index.append(f"- [{stage.title}]({specs[stage.key].filename})")
        if stage.key == "7":
            index.extend(f"  - [{child.title}]({specs[child.key].filename})" for child in children)
    return (prefix + f"\n\n## {parsed.stage_heading}\n\n" + "\n".join(index)
            + "\n\n" + rewrite_plan_links(parsed.suffix) + "\n")


def build_outputs(repo: Path, android_root: Path) -> dict[Path, str]:
    base = repo / PLAN_DIR
    catalog = api_catalog(repo)
    outputs = {}
    for source_name, folder, specs, is_android in (
        (ANDROID_SOURCE, ANDROID_FOLDER, ANDROID_SPECS, True),
        (BACKEND_SOURCE, BACKEND_FOLDER, BACKEND_SPECS, False),
    ):
        source = base / source_name
        parsed = parse_plan(source, is_android)
        directory = base / folder
        stages = list(parsed.stages)
        children = ()
        if is_android:
            stages[7], children = split_library_children(stages[7])
        for index, stage in enumerate(stages):
            spec = specs[stage.key]
            output = directory / spec.filename
            outputs[output] = render_stage(
                stage, spec, output, repo, android_root, catalog, source,
                specs[stages[index - 1].key].filename if index else None,
                specs[stages[index + 1].key].filename if index + 1 < len(stages) else None,
            )
        for index, child in enumerate(children):
            spec = specs[child.key]
            output = directory / spec.filename
            outputs[output] = render_stage(
                child, spec, output, repo, android_root, catalog, source,
                specs[children[index - 1].key].filename if index else specs["7"].filename,
                specs[children[index + 1].key].filename if index + 1 < len(children) else specs["8"].filename,
                specs["7"].filename,
            )
        outputs[directory / "README.md"] = render_readme(
            parsed, source, directory / "README.md", tuple(stages), specs, children, repo
        )
    return outputs


def validate_links(outputs: dict[Path, str]) -> None:
    for path, text in outputs.items():
        heading_positions(text)
        for target in re.findall(r"\]\((?:<([^>]+)>|([^\s)]+))\)", text):
            location = next(value for value in target if value)
            if location.startswith(("http://", "https://", "#")):
                continue
            location = location.split("#", 1)[0]
            resolved = Path(location) if re.match(r"^[A-Za-z]:/", location) else (path.parent / location).resolve()
            if resolved not in outputs and not resolved.exists():
                raise FileNotFoundError(f"Broken Markdown link in {path.name}: {location}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate generated content without writing")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--android-root", type=Path, default=DEFAULT_ANDROID_ROOT)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    try:
        outputs = build_outputs(repo, args.android_root.resolve())
        validate_links(outputs)
        changed = [path for path, text in outputs.items()
                   if not path.is_file() or path.read_text(encoding="utf-8") != text]
        if args.check:
            if changed:
                for path in changed:
                    print(f"Outdated or missing: {path.relative_to(repo)}")
                return 1
            print(f"CHECK OK: {len(outputs)} generated Markdown files; source references and endpoints verified")
            return 0
        for path in changed:
            if not path.resolve().is_relative_to(repo / PLAN_DIR):
                raise ValueError(f"Output is outside the plan directory: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(outputs[path], encoding="utf-8", newline="\n")
        print(f"Generated {len(outputs)} Markdown files in 2 folders; {len(changed)} files changed")
        print("Android: 12 main stages, 4 library substages, README")
        print("Backend OCR: 5 stages, README")
        print("Original plans preserved; frontend files and backend routes verified")
        return 0
    except (OSError, ValueError, SyntaxError) as exc:
        print(f"Split failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
