"""Schemas, prompts, and JSON parsing utilities for multi-turn AI search."""

import json
import logging
import re
from typing import Any, Dict
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

class StrictOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class LabelQuery(StrictOutput):
    kind: Literal["lcsc", "mpn", "value", "package"]
    text: str = Field(min_length=1, max_length=64)


class LabelSpecs(StrictOutput):
    package: str | None = Field(max_length=48)
    value: str | None = Field(max_length=48)
    manufacturer: str | None = Field(max_length=48)


class ExtractorOutput(StrictOutput):
    family: Literal["resistor", "capacitor", "inductor", "ic", "connector", "mechanical", "general", "unknown"]
    queries: list[LabelQuery] = Field(max_length=3)
    specs: LabelSpecs
    review_reason: str | None = Field(max_length=40)


class ExcludedCandidate(StrictOutput):
    index: int = Field(ge=1)
    reason: str = Field(max_length=80)


class RerankerOutput(StrictOutput):
    decision: Literal["exact_match", "ambiguous", "no_match"]
    selected_index: int | None = Field(ge=1)
    candidate_indices: list[int] | None = Field(max_length=10)
    reasoning: str = Field(max_length=120)
    excluded: list[ExcludedCandidate] = Field(max_length=10)


EXTRACT_SCHEMA = ExtractorOutput.model_json_schema()
RERANK_SCHEMA = RerankerOutput.model_json_schema()


class ModelOutputError(ValueError):
    def __init__(self, code, finish_reason=None):
        self.code, self.finish_reason = code, finish_reason
        super().__init__(code)


class AIStageError(RuntimeError):
    def __init__(self, stage, code, attempts=1, finish_reason=None):
        self.details = {"stage": stage, "code": code, "attempts": attempts, "finish_reason": finish_reason}
        super().__init__(f"{stage}: {code} (attempts={attempts})")


def structured_format(name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap JSON Schema into OpenAI-compatible response_format specification."""
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def completed_json(response: Any, output_model=None) -> Dict[str, Any]:
    """Validate completion finish reason and extract validated JSON payload."""
    if not response.choices or response.choices[0].finish_reason != "stop":
        finish = response.choices[0].finish_reason if response.choices else None
        raise ModelOutputError("output_incomplete", finish)
    try:
        parsed = json.loads(response.choices[0].message.content or "")
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError()
        if output_model is not None:
            parsed = output_model.model_validate(parsed).model_dump()
    except (ValueError, TypeError, ValidationError) as exc:
        raise ModelOutputError("invalid_output", "stop") from exc
    return parsed


def request_structured(client, stage, model, messages, output_model, schema, budget):
    """Retry a truncated text completion once, never OCR and never a hidden heuristic."""
    for attempt in (1, 2):
        try:
            response = client.chat.completions.create(model=model, messages=messages,
                temperature=0.1, max_tokens=budget, response_format=structured_format(stage, schema))
        except Exception as exc:
            raise AIStageError(stage, "model_unavailable", attempt) from exc
        try:
            parsed = completed_json(response, output_model)
        except ModelOutputError as exc:
            if exc.finish_reason == "length" and attempt == 1:
                continue
            raise AIStageError(stage, exc.code, attempt, exc.finish_reason) from exc
        parsed["stage_status"] = {"stage": stage, "status": "complete", "attempts": attempt,
                                  "finish_reason": "stop", "budget": budget}
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
