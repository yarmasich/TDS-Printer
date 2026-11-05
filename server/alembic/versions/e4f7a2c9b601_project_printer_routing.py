"""Integration-bound project printer policy; legacy keys retain legacy scopes only.

Revision ID: e4f7a2c9b601
Revises: e91b2c7d0436
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f7a2c9b601'
down_revision = 'e91b2c7d0436'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('integration', sa.Column('id', sa.String(), primary_key=True),
                    sa.Column('name', sa.String(), nullable=False, unique=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    with op.batch_alter_table('apikey') as batch:
        batch.add_column(sa.Column('integration_id', sa.String(), nullable=True))
        batch.add_column(sa.Column('scopes', sa.JSON(), nullable=False, server_default='["legacy_catalog", "legacy_print"]'))
        batch.create_foreign_key('fk_apikey_integration', 'integration', ['integration_id'], ['id'])
        batch.create_index('ix_apikey_integration_id', ['integration_id'])
    op.create_table('projectprintpolicy',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('integration_id', sa.String(), sa.ForeignKey('integration.id'), nullable=False),
        sa.Column('external_project_id', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('tds_project_id', sa.Integer(), sa.ForeignKey('project.id')),
        sa.Column('cable_default_printer_id', sa.Integer(), sa.ForeignKey('printer.id')),
        sa.Column('qr_default_printer_id', sa.Integer(), sa.ForeignKey('printer.id')),
        sa.UniqueConstraint('integration_id', 'external_project_id'),
        sa.CheckConstraint('revision > 0', name='ck_policy_revision'))
    op.create_index('ix_projectprintpolicy_integration_id', 'projectprintpolicy', ['integration_id'])
    op.create_table('projectprinterassignment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('policy_id', sa.String(), sa.ForeignKey('projectprintpolicy.id'), nullable=False),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('printer_id', sa.Integer(), sa.ForeignKey('printer.id'), nullable=False),
        sa.UniqueConstraint('policy_id', 'purpose', 'printer_id'),
        sa.CheckConstraint("purpose IN ('cable_labels','qr_labels')", name='ck_assignment_purpose'))
    op.create_index('ix_projectprinterassignment_policy_id', 'projectprinterassignment', ['policy_id'])
    op.create_index('ix_projectprinterassignment_printer_id', 'projectprinterassignment', ['printer_id'])
    op.create_table('policyaudit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('integration_id', sa.String(), sa.ForeignKey('integration.id'), nullable=False),
        sa.Column('external_project_id', sa.String(), nullable=False),
        sa.Column('actor', sa.String(), nullable=False), sa.Column('ts', sa.DateTime(), nullable=False),
        sa.Column('before', sa.JSON(), nullable=False), sa.Column('after', sa.JSON(), nullable=False))
    for name in ('integration_id', 'external_project_id', 'print_purpose'):
        op.add_column('printlog', sa.Column(name, sa.String(), nullable=False, server_default=''))


def downgrade():
    # Dropping integration identities would allow old physical-send reservations
    # to lose their credential namespace. Require an explicit operational export
    # and migration rather than silently permitting this unsafe rollback.
    scoped_keys = op.get_bind().execute(sa.text('SELECT COUNT(*) FROM apikey WHERE integration_id IS NOT NULL')).scalar()
    if scoped_keys:
        raise RuntimeError('Cannot downgrade project routing with scoped credentials; revoke and delete them first')
    bound = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM integrationprintrequest WHERE credential_hash LIKE 'integration:%'")).scalar()
    if bound:
        raise RuntimeError('Cannot downgrade project routing with permanent scoped print reservations')
    with op.batch_alter_table('printlog') as batch:
        for name in ('integration_id', 'external_project_id', 'print_purpose'):
            batch.drop_column(name)
    op.drop_table('policyaudit')
    op.drop_table('projectprinterassignment')
    op.drop_table('projectprintpolicy')
    with op.batch_alter_table('apikey') as batch:
        batch.drop_index('ix_apikey_integration_id')
        batch.drop_constraint('fk_apikey_integration', type_='foreignkey')
        batch.drop_column('scopes')
        batch.drop_column('integration_id')
    op.drop_table('integration')
