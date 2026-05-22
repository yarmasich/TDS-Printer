"""drop Template.mirror_mode

The mirror_mode flag was a port of the Android app's drawMirrorText
behaviour, but it never lined up with what PANDUIT EasyMark produces
for wrap-around labels and ended up confusing the operator instead of
helping. Drop the column outright rather than carrying dead state.

Revision ID: 9a4c2b1d7e30
Revises: 232e2ff8080e
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op


revision = "9a4c2b1d7e30"
down_revision = "232e2ff8080e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite drops the column by recreating the table. While the
    # placeholder table exists the discipline.template_id FK would
    # spuriously fail, so disable FK enforcement just for this op.
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("template") as batch:
        batch.drop_column("mirror_mode")
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    import sqlalchemy as sa
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("template") as batch:
        batch.add_column(
            sa.Column("mirror_mode", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute("PRAGMA foreign_keys=ON")
