"""Preserve stable external employee identity in print history."""
from alembic import op
import sqlalchemy as sa

revision = 'b7e2d9a43f10'
down_revision = 'f1c4a7d92e60'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('printlog', sa.Column('operator_employee_id', sa.String(), nullable=True))


def downgrade():
    op.drop_column('printlog', 'operator_employee_id')
