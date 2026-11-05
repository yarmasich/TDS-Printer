"""Per-printer status settings and QR label defaults."""
from alembic import op
import sqlalchemy as sa
revision = 'f2c8d1b90376'
down_revision = 'e4f7a2c9b601'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('printer', sa.Column('snmp_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('printer', sa.Column('snmp_port', sa.Integer(), nullable=False, server_default='161'))
    op.add_column('printer', sa.Column('snmp_community', sa.String(), nullable=True))
    op.add_column('printer', sa.Column('qr_media_id', sa.String(), nullable=False, server_default='DK-2246'))
    op.add_column('printer', sa.Column('qr_label_length_mm', sa.Integer(), nullable=False, server_default='60'))


def downgrade():
    # Native DROP COLUMN preserves incoming foreign keys (SQLite 3.35+).
    with op.batch_alter_table('printer', recreate='never') as batch:
        for name in ('qr_label_length_mm', 'qr_media_id', 'snmp_community', 'snmp_port', 'snmp_enabled'):
            batch.drop_column(name)
