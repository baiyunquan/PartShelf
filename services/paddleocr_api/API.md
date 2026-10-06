# PaddleOCR 独立 API 说明

本服务部署在 `ElectronicQwen/ocr_api`，只接收图片并返回 OCR 文字证据。它不连接 PartShelf 数据库，不查嘉立创目录，也不执行入库。PartShelf 通过 HTTP 调用，服务可部署在另一台设备。

API 版本为 `1`。交互式文档：`GET /docs`；OpenAPI：`GET /openapi.json`。

## 1. 健康检查

`GET /health`

模型加载完成后返回 HTTP 200：

```json
{"api_version":"1","ready":true,"device":"cpu"}
```

模型未就绪返回 503；启动阶段模型正在加载时，服务端口可能尚未开始接受连接。不要把进程已创建视为模型已就绪。

## 2. 图片识别

`POST /v1/ocr`

请求使用 `multipart/form-data`，必需字段为 `image`，内容为一个 JPEG、PNG 或 WebP 文件。文件最大 10 MiB，图像最大 2400 万像素；当前接口处理单张图片。

```bash
curl --fail-with-body http://127.0.0.1:8010/v1/ocr \
  -F 'image=@examples/20260927_193953.jpg'
```

HTTP 200 的响应示例：

```json
{
  "api_version": "1",
  "request_id": "98da94d1-b6bf-4c4a-86d9-3bf691b63cd8",
  "image": {"width":4000,"height":1848,"rotation_degrees":270},
  "lines": [
    {"text":"C6119867 BD","confidence":0.9543,
     "box":[[1159,633],[1536,671],[1529,740],[1152,703]]},
    {"text":"0603","confidence":0.9979,
     "box":[[1100,1000],[1200,1000],[1200,1040],[1100,1040]]}
  ],
  "alternatives": [
    {"image":{"width":1848,"height":4000,"rotation_degrees":0},"lines":[]},
    {"image":{"width":4000,"height":1848,"rotation_degrees":90},"lines":[]},
    {"image":{"width":1848,"height":4000,"rotation_degrees":180},"lines":[]},
    {"image":{"width":4000,"height":1848,"rotation_degrees":270},"lines":[]}
  ],
  "elapsed_ms": 1900.0
}
```

示例坐标和耗时用于说明格式，不是性能承诺。

| 字段 | 含义 |
|---|---|
| `api_version` | 协议版本字符串，当前为 `1` |
| `request_id` | 本次 OCR 请求的服务端 UUID，不代表入库凭证 |
| `image` | 所选识别方向下的图片宽高与顺时针旋转角度；旋转是在 EXIF 修正后进行 |
| `lines[].text` | 识别出的原始文字 |
| `lines[].confidence` | 识别置信度，范围 0–1 |
| `lines[].box` | 四点文字框，坐标相对于该识别方向下的图片，左上角为原点，x 向右、y 向下 |
| `alternatives` | 0、90、180、270 度各方向的识别证据，包含独立的 `image` 和 `lines` |
| `elapsed_ms` | 图片处理、排队等待及模型推理的耗时，单位毫秒 |

顶层 `lines` 按通用识别质量选择。核验服务可检查 `alternatives`，避免倒置的纯数字封装行影响识别。多个标签产生不同编号或封装时，应进入人工核查。

识别不到文字时也返回 HTTP 200，`lines` 可以为空。这表示识别完成，不表示标签通过业务核验。

## 3. 错误响应

错误为 JSON，使用 FastAPI 的 `detail` 字段：

```json
{"detail":"Invalid image"}
```

| HTTP 状态 | 情况 | 调用方处理 |
|---|---|---|
| 413 | 文件超过 10 MiB | 缩小图片后重试 |
| 422 | 缺少文件、文件不是有效图片、格式或像素数量不符合要求 | 修正请求或重新拍摄 |
| 503 | 模型未就绪或推理失败 | 保留待核查条目，恢复服务后重试 |

## 4. 运行与配置

Linux 首次安装：

```bash
cd ElectronicQwen
python3.11 -m venv .venv-ocr
.venv-ocr/bin/python -m pip install -r ocr_api/requirements.txt
.venv-ocr/bin/python -m uvicorn ocr_api.server:app --host 0.0.0.0 --port 8010 --workers 1
```

Windows 可使用已有的 PaddleOCR 虚拟环境：

```powershell
cd ElectronicQwen
.venv\Scripts\python.exe -m pip install -r ocr_api\requirements.txt
.venv\Scripts\python.exe -m uvicorn ocr_api.server:app --host 0.0.0.0 --port 8010 --workers 1
```

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `OCR_DEVICE` | `cpu` | 推理设备；配置 GPU 时需在 OCR 环境安装相匹配的 Paddle GPU 运行库 |
| `OCR_DET_MODEL_DIR` | PaddleOCR 默认目录 | 检测模型路径 |
| `OCR_REC_MODEL_DIR` | PaddleOCR 默认目录 | 文字识别模型路径 |
| `OCR_CLS_MODEL_DIR` | PaddleOCR 默认目录 | 文字方向分类模型路径 |

采用 PaddleOCR 2.9.1、PaddlePaddle 2.6.2、PP-OCRv4 中英文模型。首次启动会下载未缓存的模型；离线设备应提前准备三个模型目录并设置以上变量。模型每个进程加载一次，推理串行执行，默认一个 Uvicorn worker。

当前 Linux CPU 上已复现 Paddle 2.6.2 的 `self_attention_fuse_pass` 原生崩溃，服务在模型构建期间禁用该可选融合步骤，随后恢复构建函数；保留 PP-OCRv4 模型和库版本。相同崩溃见 [Paddle 官方问题记录](https://github.com/PaddlePaddle/Paddle/issues/70538)。

## 5. 对接 PartShelf

在 PartShelf 的 `.env` 中设置：

```dotenv
PADDLEOCR_API_URL=http://192.168.1.20:8010
PADDLEOCR_TIMEOUT_SECONDS=60
```

地址填写服务根地址，PartShelf 会添加 `/v1/ocr`。浏览器上传照片到 PartShelf，再由 PartShelf 转发到 OCR 服务，不需要浏览器直接连接另一台设备或配置 CORS。

核验通过后，PartShelf 自动创建一包库存及所选项目关联。OCR 超时、不可用、字段缺失或冲突均进入人工核查。OCR 服务不会保存上传图片；待核查图片和入库凭证由 PartShelf 保存。

## 6. 源码同步

`ElectronicQwen` 当前不属于 Git 仓库。可部署服务源码同时保存在 PartShelf 的 `services/paddleocr_api`，便于版本控制。在 PartShelf 目录执行以下命令即可更新 ElectronicQwen 中的服务：

```bash
python scripts/sync_ocr_api.py --destination ../ElectronicQwen
```

同步只复制 API 源码、依赖和文档，不复制虚拟环境、模型或已有 OCR 结果。
