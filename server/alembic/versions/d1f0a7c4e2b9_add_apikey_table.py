"""add apikey table

Revision ID: d1f0a7c4e2b9
Revises: c886c484ba4c
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  — for sqlmodel.sql.sqltypes.AutoString


# revision identifiers, used by Alembic.
revision: str = 'd1f0a7c4e2b9'
down_revision: Union[str, Sequence[str], None] = 'c886c484ba4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'apikey',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('prefix', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('key_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    with op.batch_alter_table('apikey', schema=None) as batch_op:
        batch_op.create_index('ix_apikey_prefix', ['prefix'], unique=False)
        batch_op.create_index('ix_apikey_created_at', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('apikey', schema=None) as batch_op:
        batch_op.drop_index('ix_apikey_created_at')
        batch_op.drop_index('ix_apikey_prefix')
    op.drop_table('apikey')
