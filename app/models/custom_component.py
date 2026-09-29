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
    created_at = Column(DateTime, default=datetime.utcnow)
