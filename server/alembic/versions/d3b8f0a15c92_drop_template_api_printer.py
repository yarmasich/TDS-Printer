"""drop Template.api_printer_id (no-op if column absent)

Superseded by the per-request ``printer_id`` on /api/v1: the calling
workstation names its printer per print, so the template no longer needs a
separate API-printer default — API jobs fall back to ``printer_id`` like the
web flow.

Revision ID: d3b8f0a15c92
Revises: e2a9c3f1b7d4
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

revision = "d3b8f0a15c92"
down_revision = "e2a9c3f1b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    conn = op.get_bind()
    cols = {
        row[1]
        for row in conn.execute(
            __import__("sqlalchemy").text("PRAGMA table_info(template)")
        )
    }
    if "api_printer_id" in cols:
        with op.batch_alter_table("template") as batch:
            batch.drop_column("api_printer_id")
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    import sqlalchemy as sa

    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("template") as batch:
        batch.add_column(sa.Column("api_printer_id", sa.Integer(), nullable=True))
    op.execute("PRAGMA foreign_keys=ON")
