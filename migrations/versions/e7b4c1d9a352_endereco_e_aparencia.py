"""tipo de endereço (casa, apartamento, condomínio) e opções do site

Revision ID: e7b4c1d9a352
Revises: d3a9b7e2c614
Create Date: 2026-10-29 21:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7b4c1d9a352'
down_revision = 'd3a9b7e2c614'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('fee_apartment', sa.Numeric(8, 2), nullable=True))
        b.add_column(sa.Column('fee_condo', sa.Numeric(8, 2), nullable=True))
        b.add_column(sa.Column('site_options', sa.Text(), nullable=True))
    for table in ('customers', 'orders'):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column('residence', sa.String(length=12), nullable=True))
            b.add_column(sa.Column('building', sa.String(length=120), nullable=True))


def downgrade():
    for table in ('orders', 'customers'):
        with op.batch_alter_table(table) as b:
            b.drop_column('building')
            b.drop_column('residence')
    with op.batch_alter_table('tenants') as b:
        b.drop_column('site_options')
        b.drop_column('fee_condo')
        b.drop_column('fee_apartment')
