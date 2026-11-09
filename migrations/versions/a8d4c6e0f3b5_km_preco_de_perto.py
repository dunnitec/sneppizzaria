"""preco por km de perto

Revision ID: a8d4c6e0f3b5
Revises: f7c3b5d9e2a4
Create Date: 2026-11-09 16:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8d4c6e0f3b5'
down_revision = 'f7c3b5d9e2a4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('km_near_km', sa.Numeric(6, 1), nullable=True))
        b.add_column(sa.Column('km_near_price', sa.Numeric(8, 2), nullable=True))


def downgrade():
    with op.batch_alter_table('tenants') as b:
        b.drop_column('km_near_price')
        b.drop_column('km_near_km')
