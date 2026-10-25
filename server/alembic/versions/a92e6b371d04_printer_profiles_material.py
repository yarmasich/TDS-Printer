"""Model profiles and explicit material feed; preserve existing settings."""
from alembic import op
import sqlalchemy as sa

revision = 'a92e6b371d04'
down_revision = 'f8a2d6e901bc'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('printer', sa.Column('model', sa.String(), nullable=False, server_default='custom'))
    op.add_column('template', sa.Column('media_height_mm', sa.Float(), nullable=False, server_default='0'))
    op.add_column('template', sa.Column('media_gap_mm', sa.Float(), nullable=False, server_default='3'))


def downgrade():
    with op.batch_alter_table('template') as batch:
        batch.drop_column('media_gap_mm')
        batch.drop_column('media_height_mm')
    with op.batch_alter_table('printer') as batch:
        batch.drop_column('model')
