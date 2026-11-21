"""Display name for an integration's external project on its printer policy.

Nullable and display only; routing still keys on external_project_id. The
add is guarded so a database whose table already carries the column (for
example one created by ``SQLModel.metadata.create_all``) upgrades cleanly.

Revision ID: f3b9e2c71a58
Revises: 8c41f0a2d7e5
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b9e2c71a58"
down_revision = "8c41f0a2d7e5"
branch_labels = None
depends_on = None

TABLE = "projectprintpolicy"
COLUMN = "external_project_name"


def _has_column() -> bool:
    return COLUMN in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    if not _has_column():
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(200), nullable=True))


def downgrade():
    if _has_column():
        # In place: recreating the table would trip the assignments' foreign keys.
        with op.batch_alter_table(TABLE, recreate="never") as batch:
            batch.drop_column(COLUMN)
