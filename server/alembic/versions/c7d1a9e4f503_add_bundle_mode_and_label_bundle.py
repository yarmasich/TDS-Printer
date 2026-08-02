"""add discipline bundle_mode and label bundle

Per-discipline opt-in bundle parsing. When ``discipline.bundle_mode`` is on,
imports tag each label with the ``BUNDLE #N`` it falls under (``label.bundle``)
so a whole bundle can be printed at once. Both default to off / null, so
existing disciplines and labels are unchanged.

Revision ID: c7d1a9e4f503
Revises: b5c2e4a7f019
Create Date: 2026-08-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7d1a9e4f503"
down_revision = "b5c2e4a7f019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discipline",
        sa.Column(
            "bundle_mode", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("label", sa.Column("bundle", sa.String(), nullable=True))
    op.create_index("ix_label_bundle", "label", ["bundle"])


def downgrade() -> None:
    op.drop_index("ix_label_bundle", table_name="label")
    with op.batch_alter_table("label") as batch:
        batch.drop_column("bundle")
    with op.batch_alter_table("discipline") as batch:
        batch.drop_column("bundle_mode")
