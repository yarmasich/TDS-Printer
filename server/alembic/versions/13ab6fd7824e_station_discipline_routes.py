"""Station cable printer routes by discipline."""
from alembic import op
import sqlalchemy as sa

revision = "13ab6fd7824e"
down_revision = "f2c8d1b90376"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("station", sa.Column("route_by_discipline", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "stationprinterroute",
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("station.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("discipline_id", sa.Integer(), sa.ForeignKey("discipline.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("printer_id", sa.Integer(), sa.ForeignKey("printer.id"), nullable=False),
    )
    op.create_index("ix_stationprinterroute_printer_id", "stationprinterroute", ["printer_id"])


def downgrade():
    op.drop_table("stationprinterroute")
    with op.batch_alter_table("station", recreate="never") as batch:
        batch.drop_column("route_by_discipline")
