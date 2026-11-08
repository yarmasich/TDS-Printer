"""Map template printers to local allowed station printers."""
from alembic import op
import sqlalchemy as sa

revision = "71db8e02a64c"
down_revision = "5d92ac83f6e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stationprintermap",
        sa.Column("station_id", sa.Integer(), primary_key=True),
        sa.Column("template_printer_id", sa.Integer(), sa.ForeignKey("printer.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("local_printer_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["station_id", "local_printer_id"],
            ["stationprinter.station_id", "stationprinter.printer_id"],
            ondelete="CASCADE",
        ),
    )


def downgrade():
    op.drop_table("stationprintermap")
