from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class FastenerSpecCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nominal: str = Field(min_length=1, max_length=100)
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    length: Optional[Any] = None
