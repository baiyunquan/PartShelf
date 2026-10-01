from sqlalchemy import Column, String

from db.database import Base


class WarehouseDrawer(Base):
    """Stable lockable drawer identity; placements remain the occupancy authority."""

    __tablename__ = "warehouse_drawers"

    cabinet_id = Column(String(32), primary_key=True)
    drawer_code = Column(String(16), primary_key=True)
    drawer_type = Column(String(1), nullable=False)
    group_key = Column(String(96), nullable=True)
    group_label = Column(String(255), nullable=True)
