"""Station logins, assigned printers and immutable print attribution."""
from alembic import op
import sqlalchemy as sa
revision = 'c8d1e4f63a20'
down_revision = 'b7e2d9a43f10'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('station',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('printer_id', sa.Integer(), sa.ForeignKey('printer.id'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('session_version', sa.String(), nullable=False))
    op.create_index('ix_station_username', 'station', ['username'], unique=True)
    op.add_column('printlog', sa.Column('station_id', sa.Integer(), nullable=True))
    op.add_column('printlog', sa.Column('station_name', sa.String(), nullable=False, server_default=''))
    op.add_column('printlog', sa.Column('printer_name', sa.String(), nullable=False, server_default=''))

def downgrade():
    op.drop_column('printlog', 'printer_name')
    op.drop_column('printlog', 'station_name')
    op.drop_column('printlog', 'station_id')
    op.drop_index('ix_station_username', table_name='station')
    op.drop_table('station')
