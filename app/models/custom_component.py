from datetime import datetime
from db.database import Base
from sqlalchemy import Column, Integer, String, DateTime, Text

class CustomComponent(Base):
    __tablename__ = "custom_components"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    manufacturer = Column(String(255), nullable=True)
    package = Column(String(128), nullable=True)
    part_type = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    specs = Column(Text, nullable=True)
    raw_ocr_text = Column(Text, nullable=True)
    source_scan_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
