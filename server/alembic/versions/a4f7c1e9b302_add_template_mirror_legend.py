"""add template mirror_legend

Optional per-template flag: when on, each text block is printed twice within
its rectangle (bottom upright, top rotated 180°, same text) so a
self-laminating wrap reads from either side. Defaults off — existing
single-print templates are unchanged.

Revision ID: a4f7c1e9b302
Revises: d3b8f0a15c92
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4f7c1e9b302"
down_revision = "d3b8f0a15c92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "template",
        sa.Column(
            "mirror_legend",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("template") as batch:
        batch.drop_column("mirror_legend")
