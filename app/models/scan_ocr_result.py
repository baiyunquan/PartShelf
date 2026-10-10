from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, String

from db.database import Base


class ScanOCRResult(Base):
    """A durable claim prevents the same image from being recognized by multiple workers."""
    __tablename__ = "scan_ocr_results"

    cache_key = Column(String(64), primary_key=True)
    image_sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
