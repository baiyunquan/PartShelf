from pydantic import BaseModel
from typing import List, Optional

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class ProjectPartAdd(BaseModel):
    part_id: int
    quantity_needed: Optional[int] = 0

class ProjectPartUpdate(BaseModel):
    quantity_needed: Optional[int] = 0

class ProjectPartItem(BaseModel):
    part_id: int
    part_name: str
    manufacturer: Optional[str] = None
    package: Optional[str] = None
    part_type: Optional[str] = None
    quantity_available: int = 0
    quantity_needed: Optional[int] = 0
    shortage: int = 0

class ProjectDetails(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    parts_count: int = 0
    parts: List[ProjectPartItem] = []

class ProjectListItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    parts_count: int = 0

class ProjectRef(BaseModel):
    id: int
    name: str
    quantity_needed: Optional[int] = 0

class ProcurementItem(BaseModel):
    part_id: int
    part_name: str
    manufacturer: Optional[str] = None
    package: Optional[str] = None
    part_type: Optional[str] = None
    quantity_available: int = 0
    total_needed: int = 0
    shortage: int = 0
    projects: List[ProjectRef] = []
