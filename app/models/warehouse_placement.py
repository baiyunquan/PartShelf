from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import relationship

from db.database import Base


class WarehousePlacement(Base):
    __tablename__ = "warehouse_placements"

    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), primary_key=True)
    cabinet_id = Column(String(32), nullable=False, index=True)
    drawer_code = Column(String(16), nullable=False, index=True)
    photo_data = Column(LargeBinary, nullable=False)
    photo_mime_type = Column(String(100), nullable=False)

    part = relationship("Part", back_populates="warehouse_placement")
