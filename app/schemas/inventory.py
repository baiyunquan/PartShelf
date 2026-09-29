from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class PartProjectItem(BaseModel):
    id: int
    name: str
    quantity_needed: Optional[int] = 0

class PartToInventoryAdd(BaseModel):
    library_source: str  # 'jlcparts', 'altium', 'kicad'
    external_part_id: str
    quantity: int = 1
    storage_location: Optional[str] = None
    note: Optional[str] = None
    project_ids: Optional[List[int]] = None

    # Backwards-compatible optional fields
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    part_type: Optional[str] = None
    package: Optional[str] = None
    description: Optional[str] = None

class PartInventoryQuantityUpdate(BaseModel):
    part_id: int
    quantity: int

class PartInventoryQuantity(BaseModel):
    updatedQuantity: int

class PartMetaUpdate(BaseModel):
    part_id: int
    storage_location: Optional[str] = None
    note: Optional[str] = None

class PartInventoryFlatGet(BaseModel):
    id: int
    library_source: str
    external_part_id: str
    name: str
    manufacturer: Optional[str] = None
    part_type: Optional[str] = None
    package: Optional[str] = None
    storage_location: Optional[str] = None
    note: Optional[str] = None
    quantity: Optional[int] = 0
    image_url: Optional[str] = None
    datasheet_url: Optional[str] = None
    projects: List[PartProjectItem] = []

class PartDetailsFlatGet(BaseModel):
    id: int
    library_source: str
    external_part_id: str
    name: str
    manufacturer: Optional[str] = None
    part_type: Optional[str] = None
    package: Optional[str] = None
    storage_location: Optional[str] = None
    note: Optional[str] = None
    quantity: Optional[int] = 0
    description: Optional[str] = None
    image_url: Optional[str] = None
    datasheet_url: Optional[str] = None
    projects: List[PartProjectItem] = []
    external_details: Optional[Dict[str, Any]] = None