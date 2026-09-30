# Agent Guidelines

## UI & Development Rules

- **严禁使用表情符号（No Emojis）**：
  - 在所有的前端页面（HTML 模板、组件、导航栏、按钮、徽章、弹窗、提示信息等）中，**严禁使用任何表情符号或 Emoji**（如 🌐, 🇨🇳, 🇺🇸, 🎉, ✕ 等），界面应保持专业、整洁的工业与工程化风格。
  - 在国际化多语言（i18n）词条文件中，不得包含任何表情符号，直接使用纯文本（例如“中文”、“English”）。
  - 代码注释、文档与系统提示信息中同样避免使用表情符号。

- **Git Commit 信息规范（Commit Messages in English）**：
  - Git commit 提交信息必须全部使用英文，严禁使用中文（Commit messages must be written in English only, no Chinese）。
  - 建议遵循 Conventional Commits 规范（如 `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:` 等）。

- **前端资源分离与重构规范（Asset Separation & Clean Templates）**：
  - **HTML 模板职责纯粹**：所有的 Jinja2 模板（`templates/`）必须保持轻量结构化，**严禁在 HTML 模板中内嵌大段 JavaScript（`<script>`）或 CSS（`<style>`）**。
  - **样式与脚本文件归档**：
    - 页面级样式一律保存在 `static/css/<page>.css` 中，并通过 `<link href="/static/css/<page>.css" rel="stylesheet">` 引入。
    - 交互脚本一律保存在 `static/js/<page>.js` 中，并在页面底部通过 `<script src="/static/js/<page>.js"></script>` 引入。
  - **模板与脚本参数解耦（i18n & Parameter Binding）**：
    - 多语言词条统一由服务端渲染为 JSON 数据岛（如 `<script id="page-translations" type="application/json">{{ page_translations | tojson }}</script>`），外部 `.js` 脚本统一通过 `JSON.parse(...)` 读取，严禁在外部静态 `.js` 中直接写入 Jinja2 插值表达式 `{{ ... }}`。
    - 页面参数（如元件 ID、标准代号）优先通过 DOM 元素的 `data-*` 属性（如 `data-comp-id="{{ comp_id }}"`）或 URL 路径解析获取，保持脚本的完全静态化。
  - **程序化辅助重构原则（Program-Assisted Refactoring）**：
    - 涉及批量模板瘦身、静态资源抽取或全库格式对齐等大型重构任务时，必须编写专用的自动化 Python 脚本（参考 `scripts/refactor_extract_assets.py`）辅助执行，严禁手工逐文件手搓分离，保证抽取精度与幂等性。

## 工作树与提交

- 开发修改直接在当前主工作树中完成，不创建独立 Git worktree。
- 完成用户要求的修改后创建 Git commit，提交信息使用英文 Conventional Commits 格式。
