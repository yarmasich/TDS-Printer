"""add template api_printer_id

Revision ID: e2a9c3f1b7d4
Revises: d1f0a7c4e2b9
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2a9c3f1b7d4'
down_revision: Union[str, Sequence[str], None] = 'd1f0a7c4e2b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Plain nullable column, no DB-level FK: SQLite batch-mode ``create_foreign_key``
    forces a fragile table copy-recreate. The ORM still declares the relationship
    (``Template.api_printer_id`` → ``printer.id``) and the templates API validates
    the referenced printer exists, so the constraint buys little here.
    """
    op.add_column('template', sa.Column('api_printer_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('template', schema=None) as batch_op:
        batch_op.drop_column('api_printer_id')
