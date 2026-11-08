"""Allow shared templates to use multiple printers and retire station maps."""
from alembic import op
import sqlalchemy as sa

revision = "39d48e7c15a2"
down_revision = "71db8e02a64c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("template", sa.Column("printer_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("station", sa.Column("default_printer_id", sa.Integer(), sa.ForeignKey("printer.id"), nullable=True), inline_references=True)
    op.execute("""
        UPDATE template SET printer_ids = (
            SELECT json_group_array(printer_id) FROM (
                SELECT template.printer_id AS printer_id
                UNION
                SELECT local_printer_id FROM stationprintermap
                WHERE template_printer_id = template.printer_id
            )
        )
    """)
    op.drop_table("stationprintermap")


def downgrade():
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
    with op.batch_alter_table("station", recreate="never") as batch:
        batch.drop_column("default_printer_id")
    with op.batch_alter_table("template", recreate="never") as batch:
        batch.drop_column("printer_ids")
