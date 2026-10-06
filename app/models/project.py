from sqlalchemy import Column, Index, Integer, String
from sqlalchemy.orm import relationship
from db.database import Base
from uuid import uuid4

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("uq_projects_system_key", "system_key", unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True)
    description = Column(String(255), nullable=True)
    # Only system-owned projects receive a key. Existing projects keep NULL.
    system_key = Column(String(32), nullable=True)
    identity_token = Column(String(36), nullable=True, default=lambda: str(uuid4()))

    parts = relationship("ProjectPart", back_populates="project", cascade="all, delete-orphan")
