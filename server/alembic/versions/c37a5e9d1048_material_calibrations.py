"""Per-printer physical corrections for exact material SKUs."""
from alembic import op
import sqlalchemy as sa
revision = 'c37a5e9d1048'
down_revision = 'b16d4a0c87e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('printer', sa.Column('material_calibrations', sa.JSON(), nullable=False, server_default='{}'))


def downgrade():
    with op.batch_alter_table('printer') as batch:
        batch.drop_column('material_calibrations')
