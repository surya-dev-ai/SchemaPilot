"""Workflow metadata tables for application database persistence.

Revision ID: 20261015_0001
Revises:
Create Date: 2026-10-15

These tables store plans, risk evidence, artifact references, sandbox/rollback
summaries, safety reports, approval bindings, and audit events. They do not
store source or sandbox connection strings. Generated migration artifacts stay
in backend/artifacts/generated/ and are referenced by migration_id + checksum.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "migration_workflows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("intent_summary", sa.Text(), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("migration_id", sa.String(length=32), nullable=False),
        sa.Column("artifact_checksum", sa.String(length=80), nullable=False),
        sa.Column("artifact_status", sa.String(length=32), nullable=False),
        sa.Column("artifact_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("risk_json", sa.Text(), nullable=False),
        sa.Column("sandbox_json", sa.Text(), nullable=True),
        sa.Column("rollback_json", sa.Text(), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("report_checksum", sa.String(length=80), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=80), nullable=False),
        sa.Column("eligible_for_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fully_reversible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rollback_status", sa.String(length=32), nullable=False),
        sa.Column("report_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("report_checksum", name="uq_migration_workflows_report_checksum"),
        sa.UniqueConstraint(
            "migration_id",
            "artifact_checksum",
            name="uq_workflow_artifact",
        ),
    )
    op.create_index("ix_migration_workflows_source_id", "migration_workflows", ["source_id"])
    op.create_index(
        "ix_migration_workflows_schema_fingerprint",
        "migration_workflows",
        ["schema_fingerprint"],
    )
    op.create_index("ix_migration_workflows_migration_id", "migration_workflows", ["migration_id"])
    op.create_index(
        "ix_migration_workflows_artifact_checksum",
        "migration_workflows",
        ["artifact_checksum"],
    )
    op.create_index("ix_migration_workflows_state", "migration_workflows", ["state"])
    op.create_index(
        "ix_migration_workflows_evidence_fingerprint",
        "migration_workflows",
        ["evidence_fingerprint"],
    )
    op.create_index(
        "ix_workflows_source_created",
        "migration_workflows",
        ["source_id", "created_at"],
    )

    op.create_table(
        "approval_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("migration_id", sa.String(length=32), nullable=False),
        sa.Column("artifact_checksum", sa.String(length=80), nullable=False),
        sa.Column("report_checksum", sa.String(length=80), nullable=False),
        sa.Column("target_identity", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column(
            "authentication_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("approver_identity", sa.String(length=128), nullable=True),
        sa.Column("limitation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["migration_workflows.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "workflow_id",
            "artifact_checksum",
            "report_checksum",
            "target_identity",
            name="uq_approval_binding",
        ),
    )
    op.create_index("ix_approval_records_workflow_id", "approval_records", ["workflow_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["migration_workflows.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_workflow_id", "audit_events", ["workflow_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_workflow_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_approval_records_workflow_id", table_name="approval_records")
    op.drop_table("approval_records")
    op.drop_index("ix_workflows_source_created", table_name="migration_workflows")
    op.drop_index("ix_migration_workflows_evidence_fingerprint", table_name="migration_workflows")
    op.drop_index("ix_migration_workflows_state", table_name="migration_workflows")
    op.drop_index("ix_migration_workflows_artifact_checksum", table_name="migration_workflows")
    op.drop_index("ix_migration_workflows_migration_id", table_name="migration_workflows")
    op.drop_index("ix_migration_workflows_schema_fingerprint", table_name="migration_workflows")
    op.drop_index("ix_migration_workflows_source_id", table_name="migration_workflows")
    op.drop_table("migration_workflows")
