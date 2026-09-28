from pydantic import BaseModel
from typing import List, Optional

class PartProjectItem(BaseModel):
    id: int
    name: str
    quantity_needed: Optional[int] = 0

class PartToInventoryAdd(BaseModel):
    name: str
    manufacturer: str
    part_type: str
    package: str
    quantity: int
    description: Optional[str] = None
    project_ids: Optional[List[int]] = None

class PartInventoryQuantityUpdate(BaseModel):
    part_id: int
    quantity: int

class PartInventoryQuantity(BaseModel):
    updatedQuantity: int

class PartInventoryFlatGet(BaseModel):
    id: int
    name: str
    manufacturer: Optional[str] = None
    part_type: Optional[str] = None
    package: Optional[str] = None
    quantity: Optional[int] = 0
    projects: List[PartProjectItem] = []

class PartDetailsFlatGet(BaseModel):
    id: int
    name: str
    manufacturer: Optional[str] = None
    part_type: Optional[str] = None
    package: Optional[str] = None
    quantity: Optional[int] = 0
    description: Optional[str] = None
    projects: List[PartProjectItem] = []