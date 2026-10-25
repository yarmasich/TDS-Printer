"""Track exact material SKU separately from the template name."""
from alembic import op
import sqlalchemy as sa
revision='b16d4a0c87e2'
down_revision='a92e6b371d04'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('template',sa.Column('material_sku',sa.String(),nullable=False,server_default=''))

def downgrade():
    with op.batch_alter_table('template') as batch: batch.drop_column('material_sku')
