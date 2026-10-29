"""CEP e número da loja para achar no mapa

Revision ID: f2c6a8e4b190
Revises: e7b4c1d9a352
Create Date: 2026-10-30 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2c6a8e4b190'
down_revision = 'e7b4c1d9a352'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('store_cep', sa.String(length=8), nullable=True))
        b.add_column(sa.Column('store_number', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('tenants') as b:
        b.drop_column('store_number')
        b.drop_column('store_cep')
