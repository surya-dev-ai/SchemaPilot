"""Add workflow owner and workspace visibility.

Revision ID: 20261029_0002
Revises: 20261015_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_0002"
down_revision: str | Sequence[str] | None = "20261015_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("migration_workflows", sa.Column("owner_identity", sa.String(512), nullable=True))
    op.add_column(
        "migration_workflows",
        sa.Column("visibility", sa.String(16), nullable=False, server_default="shared"),
    )
    op.create_index(
        "ix_migration_workflows_owner_identity",
        "migration_workflows",
        ["owner_identity"],
    )


def downgrade() -> None:
    op.drop_index("ix_migration_workflows_owner_identity", table_name="migration_workflows")
    op.drop_column("migration_workflows", "visibility")
    op.drop_column("migration_workflows", "owner_identity")
