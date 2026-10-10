# llama.cpp OCR API 与扫码入库接口

## 1. 服务与部署

唯一 OCR 引擎为 llama.cpp 中的 PaddleOCR-VL-1.5。模型后端默认为 `http://127.0.0.1:8083/v1`，Python 适配层为 `http://127.0.0.1:8010`。适配层使用 PartShelf 虚拟环境，不需要 PaddlePaddle 或传统 PaddleOCR；原 PP-OCRv4 服务已停用。

```bash
python scripts/download_paddleocr_vl.py
python run_linux.py --no-web
# Windows: python run_windows.py --no-web
```

仅启动适配层（模型后端需先启动）：

```bash
python -m paddleocr_vl.server --host 127.0.0.1 --port 8010 --llama-url http://127.0.0.1:8083/v1
```

配置：`LLAMA_OCR_BASE_URL` 指向模型后端；`LLAMA_OCR_TIMEOUT_SECONDS` 默认 30 秒。PartShelf 使用 `PADDLEOCR_API_URL` 指向适配层，`PADDLEOCR_TIMEOUT_SECONDS` 默认 30 秒。远程部署时替换地址。更新代码后必须重启适配层。

`GET /health` 在模型后端就绪时返回 200，否则 503。交互式文档为 `/docs`，OpenAPI 为 `/openapi.json`。

## 2. 独立图片识别

`POST /v1/ocr`，使用 multipart 字段 `image` 或 `file`。单张 JPEG、PNG、WebP，最大 10 MiB、2400 万像素。

```bash
curl --fail-with-body http://127.0.0.1:8010/v1/ocr -F 'image=@label.jpg'
```

适配层校正 EXIF 方向、按比例缩小至最长边 1536 像素，然后只向 llama.cpp 发送一次 `OCR:` 请求。无多方向识别、裁剪重扫或传统 OCR 回退。

```json
{
  "api_version": "1",
  "request_id": "c524d637-172f-4c23-aa89-d9bdc542b58d",
  "engine": "paddleocr-vl-llama.cpp",
  "region": null,
  "confidence_source": "not_provided_by_model",
  "status": "complete",
  "finish_reason": "stop",
  "error": null,
  "image": {"width": 3000, "height": 2000, "rotation_degrees": 0},
  "lines": [{"text": "AO3400C", "confidence": null, "box": null}],
  "raw_text": "AO3400C",
  "elapsed_ms": 1200,
  "usage": null
}
```

`image` 尺寸为 EXIF 校正后的原图尺寸；`rotation_degrees` 指后续额外旋转次数，当前始终为 0。llama.cpp 不返回逐行可靠置信度和坐标，因此两个字段为 `null`。`region=null` 表示没有可靠的文字区域，不能据此选择区域重扫；`confidence_source=not_provided_by_model` 表示模型未提供置信度。`usage` 为上游 token 用量，缺失时为 `null`。已有任务中的历史 OCR 响应保持原样，可能没有新增元数据字段。

`status=incomplete` 表示截断、重复文字、空结果或未正常结束；`error` 分别为 `ocr_incomplete`、`ocr_repeated`、`ocr_empty`。保留原始文字供核查，禁止自动再次 OCR。无效图像返回 422、超大文件返回 413、模型服务异常返回 503。

独立 OCR 接口每次 HTTP 请求执行一次识别，不连接业务数据库、不查询目录、不入库。扫码任务的持久化复用由下一节的 PartShelf 接口负责。

## 3. PartShelf 扫码任务

`POST /api/scan/recognize`：multipart `image` 必需；`qr_text` 默认空；`request_id` 为可选 UUID；`project_id` 为可选项目 ID。可用 `qr_texts` 传最多八个二维码原文组成的 JSON 数组。

- 嘉立创 `{pc:C541722,pm:AO3400C,qty:5,...}`：按 C 编号准确查询本地目录，缺失则远程拉取并缓存。数量有效时直接入库并关联原项目，**零 OCR、零 AI 调用**。型号描述不作核验依据。
- 缺失有效数量、多个嘉立创码或目录不可用：返回 `needs_review`，不调用 OCR。
- 无有效嘉立创码：使用 llama.cpp 一次识别；提取与重排只接收保存的文本。数据库按图片摘要和模型版本合并并发识别及重复上传。无读到的参数不得推测，型号后缀必须保留。

响应保留现有扫描结构，含 `status`、`label`、`component`、`ocr`、`verification`、项目快照和库存 ID。状态包含 `processing`、`needs_review`、`imported`、`duplicate`。元件和候选统一包含 `library_source`、`external_part_id`；动态嘉立创资料仍以 `jlcparts` 保存引用；启动升级会规范已有库存中的 `lcsc_dynamic` 来源别名，元件 ID 不变。

### 文本匹配与核验诊断

- 提取和重排使用 JSON Schema，并由严格类型检查再次校验。预算分别为 512、1200 tokens，理由最多 120 字。仅 `finish_reason=length` 允许重试一次相同文本请求；格式错误、无效候选下标、自相矛盾的裁决或服务异常进入核查。文本请求重试不调用 OCR，SDK 隐式重试关闭。
- `verification.stages` 记录 `extractor`、`reranker` 的 `status`（`complete`、`not_needed` 或显式配置的 `heuristic`）、`attempts`、`budget` 和完成状态。启发式结果不能自动入库。`stage_errors` 给出 `stage`、`code`、`attempts`，截断时附 `finish_reason`；常见代码有 `output_incomplete`、`invalid_output`、`invalid_candidate_index`、`inconsistent_decision`、`model_unavailable`。
- `verification.field_evidence` 保留提取字段的原文；`verification.fields` 的型号、品牌、封装、数量和规格也有 `evidence`。每条证据包含从零开始的 `line_index` 和对应原文 `text`。字段 `matched=null` 表示缺少可比较的证据，页面显示“未知”，不虚构通过结果。
- `verification.observations` 可描述连接器的间距、针数、排数、安装方式、上下接触和接线方式。每项包含 `value`、`values` 和 `evidence`；冲突时 `value=null`。外形尺寸不当作间距，描述不转换为猜测的厂家型号。
- 检索顺序为明确 C 编号、完整型号、显式标值及封装。型号内部 OCR 空格可去除，后缀不可改变；跨库合并要求明确 C 编号关联及一致的完整型号，已知品牌、封装或标值冲突的记录分别保留。
- C/R/L 型号的一处字形误读只允许发生在至少十字符型号的前六字符内，并要求品牌、显式封装、等价标值和完整目录型号共同支持，候选唯一且检索未截短。通过时返回 `model_correction` 的 `observed`、`canonical`。缺少任一证据、后缀误读或候选截短须人工核查。关联 C 编号可调用现有远程拉取缓存，但不能用不同型号的记录替代标签。
- 数量读取原文的唯一有效整数，缺失或冲突不默认补 1；电气参数使用单位换算比较，小写电压等单位与品牌简称也参与冲突检查。多个同型号品牌在照片中无法区分、型号冲突或规格冲突均禁止自动入库。

`POST /api/scan/{id}/retry`：嘉立创路径只重试目录查询及入库；普通照片复用原 OCR 结果重做搜索。失败 OCR 不重跑；尚在识别的照片可等待完成后重试读取缓存。识别任务异常中断超过恢复边界（至少 180 秒，或配置超时加 30 秒）后，保存 `ocr_interrupted` 终态，要求核查或重新拍照，不再次 OCR。

`POST /api/scan/{id}/confirm`：人工核查后提交，例如：

```json
{"library_source":"altium","external_part_id":"31355","quantity":100,"note":"Checked label","new_package":false}
```

`library_source` 支持 `jlcparts`、`altium`、`kicad`，须与 `external_part_id` 成对提供；兼容旧请求 `{"lcsc_code":"C541722","quantity":5}`。数量为 1 到 2147483647 的整数。重复包装须显式 `new_package=true`；同一任务重复确认不重复增加库存。

库存、项目明细、成员历史及扫描状态在同一事务内提交。项目身份快照防止已删除项目的 ID 被复用。列表为 `GET /api/scan/history`，项目选项为 `GET /api/scan/projects`，图片为 `GET /api/scan/{id}/image`。

主应用也提供 `/v1/ocr`、`/api/ocr/ocr` 兼容转发入口，使用同一 llama.cpp 适配层。用户名归属沿用现有 Cookie 模式。

`PADDLEOCR_VL_CACHE_VERSION` 默认 `vl-1.5-exif-1536-jpeg92-v1`。模型或预处理规则变更时更换版本，新任务使用新的识别缓存；已有任务重试仍保留其原 OCR 证据。

## 4. 离线审计与样本复验

只读历史身份审计：

```bash
python scripts/audit_scan_identities.py --database partshelf.db --report data/evaluations/identity-audit.json
```

源数据库以 SQLite 只读 URI 打开；`issues` 列出库存与扫描证据的来源/ID 不一致及疑似跨库数字 ID 复用。脚本不猜测修复。`legacy_source_aliases` 列出已知旧来源名；`missing_inventory_references` 单列库存记录缺失，删除库存也会出现这种情况，不能直接认定为身份错误。

复用已保存 llama.cpp OCR 的样本评估：

```bash
python scripts/evaluate_scan_samples.py --samples ../new_item \
  --saved-scans data/evaluations/saved-scans.json --library-dir data/libraries \
  --output data/evaluations/results.json --work-dir data/evaluations/runs
```

输入为 `[{"filename":"label.jpg","scan":{...}}]` 或本脚本生成的报告（包含 `results` 数组）。普通照片必须有与当前文件一致的 `scan.label.image_sha256` 和 `engine=paddleocr-vl-llama.cpp` 的保存结果；缺失证据就报错，不重新识别。脚本创建独立业务库、目录只读备份和项目，用现有扫描接口运行，禁用所有 OCR 调用；文本模型须可用，远程缓存只写入目录副本。输出保留每张图片的响应、候选、字段证据、核验原因及调用次数，可再次作为输入。二维码输入复用已解码的标签，该工具本身不验证浏览器二维码解码器。报告及运行目录应持久保存，避免临时目录清理后丢失证据。
