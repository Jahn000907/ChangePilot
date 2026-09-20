"""Audit schema models: append-only audit events.

Field types, constraints and indexes follow design doc v0.4 section 50 as the
single source of truth.

``audit.audit_events`` is append-only: nothing in the design provides a business
DELETE or an UPDATE path, and a correction is recorded as a new event. That rule
is a governance rule for the future audit layer, not something a column
constraint can express.

``case_id`` and ``run_id`` are plain UUID columns without foreign keys, matching
the design: the audit trail must survive independently of the rows it describes.
The design names one column ``metadata``; because ``metadata`` is reserved by
the SQLAlchemy declarative API, the Python attribute is called
``event_metadata`` while the database column keeps the documented name.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres.base import Base

AUDIT_SCHEMA = "audit"


class AuditEvent(Base):
    """One immutable audit event (v0.4 section 50)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('HUMAN', 'AGENT', 'SYSTEM')",
            name="ck_audit_events_actor_type",
        ),
        Index("ix_audit_events_case_id", "case_id"),
        Index("ix_audit_events_run_id", "run_id"),
        Index("ix_audit_events_object_type_object_id", "object_type", "object_id"),
        Index("ix_audit_events_actor_type", "actor_type"),
        Index("ix_audit_events_created_at", "created_at"),
        {"schema": AUDIT_SCHEMA},
    )

    audit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_type: Mapped[str] = mapped_column(String(60), nullable=False)
    object_id: Mapped[str] = mapped_column(String(150), nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
