"""Auto Fit and typography spacing; preserve legacy rendering by default."""
from alembic import op
import sqlalchemy as sa
revision='d48b6f0e2159'
down_revision='c37a5e9d1048'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('template',sa.Column('auto_fit',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('template',sa.Column('min_font_pt',sa.Float(),nullable=False,server_default='4'))
    op.add_column('template',sa.Column('letter_spacing_px',sa.Float(),nullable=False,server_default='0'))
    op.add_column('template',sa.Column('line_spacing_px',sa.Float(),nullable=True))

def downgrade():
    with op.batch_alter_table('template') as batch:
        for name in ['line_spacing_px','letter_spacing_px','min_font_pt','auto_fit']: batch.drop_column(name)
