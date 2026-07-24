"""add printer dpi

Printhead resolution per printer. DP4300H = 300, DP4600H = 600. cab places a
downloaded bitmap one dot per printer dot (no DPI scaling of its own), so the
JScript raster is rendered at this density — a 600-DPI head then prints at the
same physical label size as a 300-DPI one. Defaults 300, so existing rows keep
their current behaviour.

Revision ID: b5c2e4a7f019
Revises: a4f7c1e9b302
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5c2e4a7f019"
down_revision = "a4f7c1e9b302"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "printer",
        sa.Column("dpi", sa.Integer(), nullable=False, server_default="300"),
    )


def downgrade() -> None:
    with op.batch_alter_table("printer") as batch:
        batch.drop_column("dpi")
