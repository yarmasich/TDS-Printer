"""Link leg labels to their trunk labels by trunk number."""
from alembic import op
import sqlalchemy as sa

revision = "8c41f0a2d7e5"
down_revision = "39d48e7c15a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("label", sa.Column("trunk_no", sa.String(), nullable=True))
    op.add_column("label", sa.Column("leg_no", sa.String(), nullable=True))
    # Every "with trunk" print looks up one discipline's trunk by number.
    op.create_index("ix_label_discipline_trunk", "label", ["discipline_id", "trunk_no"])
    op.add_column("discipline", sa.Column("trunk_discipline_id", sa.Integer(),
                                          sa.ForeignKey("discipline.id"), nullable=True),
                  inline_references=True)


def downgrade():
    # Dropped in place like station.default_printer_id: recreating the table
    # would trip the labels' foreign keys to it.
    with op.batch_alter_table("discipline", recreate="never") as batch:
        batch.drop_column("trunk_discipline_id")
    op.drop_index("ix_label_discipline_trunk", table_name="label")
    with op.batch_alter_table("label", recreate="never") as batch:
        batch.drop_column("leg_no")
        batch.drop_column("trunk_no")
