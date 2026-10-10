# 已停用的 PP-OCR API

原 PP-OCRv4 / PaddlePaddle 服务默认推理入口已禁用，源码与旧依赖文件仅供历史参考，不再作为 PartShelf 部署依赖，也没有 OCR 回退路径。

当前唯一启用的 OCR 是 llama.cpp PaddleOCR-VL。部署、HTTP 接口、响应字段及扫码任务复用规则见 [当前 OCR API 文档](../../paddleocr_vl/API.md)。

不要按此目录旧版本的说明安装或启动 PP-OCR。已有外部服务应按进程身份或服务名停用，避免关闭端口 8010 上的当前 llama.cpp HTTP 适配层。
