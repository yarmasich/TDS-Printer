"""Durable integration print reservations.

Revision ID: a6d9b2e71c40
Revises: d48b6f0e2159
"""
from alembic import op
import sqlalchemy as sa

revision = "a6d9b2e71c40"
down_revision = "d48b6f0e2159"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integrationprintrequest",
        sa.Column("credential_hash", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("credential_hash", "idempotency_key"),
    )


def downgrade():
    op.drop_table("integrationprintrequest")
