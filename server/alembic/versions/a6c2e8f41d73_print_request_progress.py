"""Live progress counters on an integration print request.

Nullable and informational: a scoped cable-label send records how many labels are
due and how many it has handed to the printer, so the caller can show progress while
the request is still running. Guarded like f3b9e2c71a58 so a database created by
``SQLModel.metadata.create_all`` upgrades cleanly.

Revision ID: a6c2e8f41d73
Revises: f3b9e2c71a58
"""
from alembic import op
import sqlalchemy as sa

revision = "a6c2e8f41d73"
down_revision = "f3b9e2c71a58"
branch_labels = None
depends_on = None

TABLE = "integrationprintrequest"
COLUMNS = ("progress_total", "progress_sent")


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    existing = _columns()
    for name in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade():
    existing = _columns()
    with op.batch_alter_table(TABLE, recreate="never") as batch:
        for name in COLUMNS:
            if name in existing:
                batch.drop_column(name)
