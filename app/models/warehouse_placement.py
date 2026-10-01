from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import MEDIUMBLOB

from db.database import Base


class WarehousePlacement(Base):
    __tablename__ = "warehouse_placements"

    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), primary_key=True)
    cabinet_id = Column(String(32), nullable=False, index=True)
    drawer_code = Column(String(16), nullable=False, index=True)
    photo_data = Column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=False)
    photo_mime_type = Column(String(100), nullable=False)

    part = relationship("Part", back_populates="warehouse_placement")
