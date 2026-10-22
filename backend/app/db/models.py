"""Application-metadata tables. These models never describe a target database apply."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MigrationWorkflow(Base):
    __tablename__ = "migration_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent_summary: Mapped[str] = mapped_column(Text, nullable=False)
    schema_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    migration_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_checksum: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    artifact_status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    artifact_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    risk_json: Mapped[str] = mapped_column(Text, nullable=False)
    sandbox_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_checksum: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    evidence_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    eligible_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fully_reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_status: Mapped[str] = mapped_column(String(32), nullable=False)
    report_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    approvals: Mapped[list["ApprovalRecord"]] = relationship(back_populates="workflow")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="workflow")

    __table_args__ = (
        UniqueConstraint("migration_id", "artifact_checksum", name="uq_workflow_artifact"),
        Index("ix_workflows_source_created", "source_id", "created_at"),
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("migration_workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    migration_id: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    report_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    target_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    authentication_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approver_identity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    limitation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    workflow: Mapped[MigrationWorkflow] = relationship(back_populates="approvals")

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "artifact_checksum",
            "report_checksum",
            "target_identity",
            name="uq_approval_binding",
        ),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("migration_workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    workflow: Mapped[MigrationWorkflow | None] = relationship(back_populates="audit_events")
