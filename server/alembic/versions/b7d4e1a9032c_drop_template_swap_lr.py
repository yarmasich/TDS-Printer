"""drop Template.swap_lr (no-op if column absent)

Revision ID: b7d4e1a9032c
Revises: 9a4c2b1d7e30
Create Date: 2026-05-22
"""
from __future__ import annotations

from alembic import op

revision = "b7d4e1a9032c"
down_revision = "9a4c2b1d7e30"
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
    if "swap_lr" in cols:
        with op.batch_alter_table("template") as batch:
            batch.drop_column("swap_lr")
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    import sqlalchemy as sa

    op.execute("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("template") as batch:
        batch.add_column(
            sa.Column("swap_lr", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute("PRAGMA foreign_keys=ON")
