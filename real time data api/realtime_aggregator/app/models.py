from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, JSON,
    DateTime, Index, func, Text,
)
from app.database import Base


class DataRecord(Base):
    __tablename__ = "data_records"

    id          = Column(Integer, primary_key=True)
    source_key  = Column(String(100), nullable=False)
    source_url  = Column(String(500), nullable=False)
    external_id = Column(Integer, nullable=True)
    payload     = Column(JSON, nullable=False)
    checksum    = Column(String(64), nullable=True)   # SHA-256 of payload
    fetched_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_source_key", "source_key"),
        Index("ix_source_ext", "source_key", "external_id", unique=True),
    )


class FetchAudit(Base):
    __tablename__ = "fetch_audits"

    id              = Column(Integer, primary_key=True)
    source_url      = Column(String(500), nullable=False)
    source_key      = Column(String(100), nullable=False)
    status          = Column(String(20), nullable=False)
    records_fetched = Column(Integer, default=0)
    records_changed = Column(Integer, default=0)       # how many were new/updated
    duration_ms     = Column(Integer, nullable=True)
    error_detail    = Column(Text, nullable=True)
    triggered_by    = Column(String(50), default="manual")  # manual | scheduler
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_source", "source_key"),
        Index("ix_audit_created", "created_at"),
    )
