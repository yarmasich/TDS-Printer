"""add Template.scale_x

Revision ID: c3e8f1a2045b
Revises: b7d4e1a9032c
Create Date: 2026-05-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3e8f1a2045b"
down_revision = "b7d4e1a9032c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("template") as batch:
        batch.add_column(
            sa.Column("scale_x", sa.Float(), nullable=False, server_default="1")
        )
    op.execute("PRAGMA foreign_keys=ON")
    # Keep prior Turn-Tell tuning (160×638 @ 300 DPI).
    op.execute(
        "UPDATE template SET scale_x = 1.12 "
        "WHERE bytes_per_row = 160 AND height = 638"
    )


def downgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("template") as batch:
        batch.drop_column("scale_x")
    op.execute("PRAGMA foreign_keys=ON")
