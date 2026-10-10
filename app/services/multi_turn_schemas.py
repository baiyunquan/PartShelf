"""Schemas, prompts, and JSON parsing utilities for multi-turn AI search."""

import json
import logging
import re
from typing import Any, Dict

LOGGER = logging.getLogger(__name__)

EXTRACTOR_SYSTEM_PROMPT = """你是一个专业的电子元器件标签分析与实体抽取引擎。
你的任务是从杂乱的工业包装袋 OCR 文本中提取标准型号、C 码、品牌、封装与规格属性。
规则约束：
1. 过滤立创销售订单编号 (SO\\d+) 与仓库拣货库位编号 (\\d{4}-\\w+, \\d+/\\d+)。
2. 只能提取原文实际出现的型号与参数，不得推测封装、电压、品类或修改型号字符。多个型号或数量并存时记录冲突，不得猜测哪张标签有效。
3. 保留完整型号后缀。缺失的规格使用 null。输出符合给定 JSON Schema 的 JSON。"""

RERANKER_SYSTEM_PROMPT = """你是一个资深的电子硬件工程仲裁专家。
你的任务是在候选元器件列表中进行深层工程比对。
规则约束：
1. 逐项审查型号、品牌、封装兼容性、引脚数与电气参数。
2. 型号后缀不同不能判为精确匹配。多标签冲突须人工核查，不得猜测标签的新旧关系。
3. 决策分为 exact_match、ambiguous、no_match，并给出严谨的排他分析理由 (reasoning)。
4. 输出符合给定 JSON Schema 的 JSON，reasoning 不超过 120 字，不输出长篇思考过程。"""


def extract_json_safely(text: str) -> Dict[str, Any]:
    """Extract first valid balanced JSON object from model output."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return {}


SPEC_FIELDS = (
    "package", "value", "manufacturer", "resistance", "capacitance", "inductance",
    "voltage", "voltage_rating", "current", "power", "power_rating", "tolerance"
)

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "family": {"type": "string", "enum": ["resistor", "capacitor", "inductor", "ic", "connector", "mechanical", "general", "unknown"]},
        "queries": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"kind": {"type": "string", "enum": ["lcsc", "mpn", "value", "package"]},
                           "text": {"type": "string", "maxLength": 64}}, "required": ["kind", "text"]}},
        "specs": {"type": "object", "additionalProperties": False,
                  "properties": {key: {"type": ["string", "null"], "maxLength": 48} for key in ("package", "value", "manufacturer")},
                  "required": ["package", "value", "manufacturer"]},
        "review_reason": {"type": ["string", "null"], "maxLength": 40}},
    "required": ["family", "queries", "specs", "review_reason"]}

RERANK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["exact_match", "ambiguous", "no_match"]},
        "selected_index": {"type": ["integer", "null"], "minimum": 1},
        "candidate_indices": {"type": ["array", "null"], "items": {"type": "integer", "minimum": 1}, "maxItems": 10},
        "reasoning": {"type": "string", "maxLength": 120},
        "excluded": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"index": {"type": "integer", "minimum": 1}, "reason": {"type": "string", "maxLength": 80}},
            "required": ["index", "reason"]}}},
    "required": ["decision", "selected_index", "candidate_indices", "reasoning", "excluded"]}


def structured_format(name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap JSON Schema into OpenAI-compatible response_format specification."""
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def completed_json(response: Any) -> Dict[str, Any]:
    """Validate completion finish reason and extract validated JSON payload."""
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise ValueError("Model output is incomplete")
    parsed = extract_json_safely(response.choices[0].message.content or "")
    if not parsed:
        raise ValueError("Model did not return a valid JSON object")
    return parsed


def is_logistics_or_shelf_noise(s: str) -> bool:
    """Negative patterns for logistics, picking racks, sorting slots, and internal barcodes."""
    s_clean = s.strip()
    # SO26... (JLCPCB sales order number)
    if re.match(r"^SO\d+", s_clean, re.I):
        return True
    # Rack / bin / shelf codes e.g. 0703-0204, 3240-B-D07-001, 3229-B-E04-002, 2352-B-D08-003
    if re.match(r"^\d{4}[-/][A-Za-z0-9]", s_clean):
        return True
    # Sorting slot tickets e.g. 3153/29, 2123/4, 2125/15, 3323/18, 4148/13, 2/27, 18/27
    if re.match(r"^\d{1,4}/\d{1,3}\.?$", s_clean):
        return True
    # Pure numeric barcodes or line numbers e.g. 18, 5004454, 4759797, 88163, 136962
    if re.match(r"^\d{1,10}$", s_clean):
        return True
    # Barcode artifacts e.g. BARCODE-111, PLAIN-BARCODE-12345
    if re.search(r"BARCODE", s_clean, re.I):
        return True
    # Cabinet tags e.g. 柜号: 15, 批次: 123456
    if re.match(r"^(?:柜号|批次|单据号|数量|QTY)[:：]?", s_clean):
        return True
    return False
