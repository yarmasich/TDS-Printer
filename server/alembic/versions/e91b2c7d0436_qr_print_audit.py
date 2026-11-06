"""QR attempts share the existing print history without using cable text fields."""
from alembic import op
import sqlalchemy as sa

revision = 'e91b2c7d0436'
down_revision = 'c8d1e4f63a20'
branch_labels = None
depends_on = None


def upgrade():
    for name, default in [('label_kind', 'cable'), ('qr_scan', ''), ('media_code', ''),
                          ('printer_model', ''), ('source_reference', '')]:
        op.add_column('printlog', sa.Column(name, sa.String(), nullable=False, server_default=default))


def downgrade():
    with op.batch_alter_table('printlog') as batch:
        for name in ['label_kind', 'qr_scan', 'media_code', 'printer_model', 'source_reference']:
            batch.drop_column(name)
