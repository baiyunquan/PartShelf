from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from db.database import Base


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id = Column(String(36), primary_key=True)
    request_id = Column(String(36), nullable=False, unique=True)
    fingerprint = Column(String(64), nullable=False, index=True)
    # A nullable unique claim makes automatic package imports exactly once.
    # An explicitly confirmed additional physical bag leaves this NULL.
    claim_key = Column(String(64), nullable=True, unique=True)
    status = Column(String(32), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    imported_at = Column(DateTime, nullable=True)
    username = Column(Text, nullable=True)
    imported_by = Column(Text, nullable=True)
    project_id = Column(Integer, nullable=True, index=True)
    project_token = Column(String(36), nullable=True)
    project_name = Column(String(255), nullable=True)
    part_id = Column(Integer, nullable=True)
    image_filename = Column(String(80), nullable=False)
    label = Column(JSON, nullable=False)
    component = Column(JSON, nullable=True)
    ocr = Column(JSON, nullable=True)
    verification = Column(JSON, nullable=False)
    quantity = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
