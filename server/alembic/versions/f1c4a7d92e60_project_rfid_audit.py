"""Project RFID policy and immutable print identity snapshots."""
from alembic import op
import sqlalchemy as sa

revision = 'f1c4a7d92e60'
down_revision = 'a6d9b2e71c40'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('project', sa.Column('require_rfid', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('printlog', sa.Column('project_id', sa.Integer(), nullable=True))
    op.add_column('printlog', sa.Column('project_name', sa.String(), nullable=False, server_default=''))
    op.add_column('printlog', sa.Column('operator_source', sa.String(), nullable=False, server_default='manual'))
    op.add_column('printlog', sa.Column('operator_verified', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    for name in ('operator_verified', 'operator_source', 'project_name', 'project_id'):
        op.drop_column('printlog', name)
    op.drop_column('project', 'require_rfid')
