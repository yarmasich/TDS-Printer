"""Persist cart print claims and uncertain outcomes.

Revision ID: f8a2d6e901bc
Revises: c7d1a9e4f503
"""
from alembic import op
import sqlalchemy as sa

revision = "f8a2d6e901bc"
down_revision = "c7d1a9e4f503"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cartitem", sa.Column("status", sa.String(), nullable=False, server_default="queued"))
    op.add_column("cartitem", sa.Column("error", sa.String(), nullable=False, server_default=""))
    op.add_column("cartitem", sa.Column("claim_token", sa.String(), nullable=False, server_default=""))
    op.add_column("cartitem", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_cartitem_status", "cartitem", ["status"])
    op.create_index("ix_cartitem_claim_token", "cartitem", ["claim_token"])


def downgrade():
    op.drop_index("ix_cartitem_claim_token", table_name="cartitem")
    op.drop_index("ix_cartitem_status", table_name="cartitem")
    with op.batch_alter_table("cartitem") as batch:
        for column in ("claimed_at", "claim_token", "error", "status"):
            batch.drop_column(column)
