from datetime import datetime
from db.database import Base
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship

class Part(Base):
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, index=True)
    library_source = Column(String(32), nullable=False, index=True)  # 'jlcparts', 'altium', 'kicad', 'custom'
    external_part_id = Column(String(64), nullable=False, index=True)
    storage_location = Column(String(128), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inventory = relationship("Inventory", back_populates="part", uselist=False, cascade="all, delete-orphan")
    project_parts = relationship("ProjectPart", back_populates="part", cascade="all, delete-orphan")
    warehouse_placement = relationship(
        "WarehousePlacement", back_populates="part", uselist=False,
        cascade="all, delete-orphan"
    )
