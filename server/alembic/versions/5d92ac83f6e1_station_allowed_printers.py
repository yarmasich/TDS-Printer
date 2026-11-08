"""Replace station routes with allowed template printers."""
from alembic import op
import sqlalchemy as sa

revision = "5d92ac83f6e1"
down_revision = "13ab6fd7824e"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TEMPORARY TABLE station_printer_upgrade AS
        SELECT id AS station_id, printer_id FROM station WHERE NOT route_by_discipline
        UNION
        SELECT r.station_id, r.printer_id FROM stationprinterroute r
        JOIN station s ON s.id = r.station_id WHERE s.route_by_discipline
    """)
    op.drop_table("stationprinterroute")
    with op.batch_alter_table("station") as batch:
        batch.drop_column("printer_id")
        batch.drop_column("route_by_discipline")
    op.create_table(
        "stationprinter",
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("station.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("printer_id", sa.Integer(), sa.ForeignKey("printer.id"), primary_key=True),
    )
    op.create_index("ix_stationprinter_printer_id", "stationprinter", ["printer_id"])
    op.execute("INSERT INTO stationprinter SELECT station_id, printer_id FROM station_printer_upgrade")
    op.execute("DROP TABLE station_printer_upgrade")


def downgrade():
    # The earlier schema cannot represent an allowlist. Reconstruct matching
    # discipline routes from templates and choose a fixed printer for rollback.
    connection = op.get_bind()
    if connection.execute(sa.text("""
        SELECT 1 FROM station s WHERE NOT EXISTS
        (SELECT 1 FROM stationprinter p WHERE p.station_id = s.id)
    """)).first():
        raise RuntimeError("Assign a printer to every station before downgrading")
    op.execute("CREATE TEMPORARY TABLE station_printer_downgrade AS SELECT * FROM stationprinter")
    op.drop_table("stationprinter")
    op.add_column("station", sa.Column("printer_id", sa.Integer(), nullable=True))
    op.add_column("station", sa.Column("route_by_discipline", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""
        UPDATE station SET printer_id = (SELECT MIN(p.printer_id) FROM station_printer_downgrade p WHERE p.station_id = station.id),
            route_by_discipline = (SELECT COUNT(*) > 1 FROM station_printer_downgrade p WHERE p.station_id = station.id)
    """)
    with op.batch_alter_table("station") as batch:
        batch.alter_column("printer_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_station_printer_id", "printer", ["printer_id"], ["id"])
    op.create_table(
        "stationprinterroute",
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("station.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("discipline_id", sa.Integer(), sa.ForeignKey("discipline.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("printer_id", sa.Integer(), sa.ForeignKey("printer.id"), nullable=False),
    )
    op.create_index("ix_stationprinterroute_printer_id", "stationprinterroute", ["printer_id"])
    op.execute("""
        INSERT INTO stationprinterroute SELECT p.station_id, d.id, p.printer_id
        FROM station_printer_downgrade p JOIN template t ON t.printer_id = p.printer_id
        JOIN discipline d ON d.template_id = t.id
    """)
    op.execute("DROP TABLE station_printer_downgrade")
