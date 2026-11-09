"""tempo mínimo e máximo de entrega e de retirada

Revision ID: d5a1f3b7c9e2
Revises: c4e8a2f6b1d7
Create Date: 2026-11-09 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5a1f3b7c9e2'
down_revision = 'c4e8a2f6b1d7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('eta_min_minutes', sa.Integer(), nullable=True))
        b.add_column(sa.Column('pickup_min_minutes', sa.Integer(), nullable=True))
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('eta_min_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('orders') as b:
        b.drop_column('eta_min_at')
    with op.batch_alter_table('tenants') as b:
        b.drop_column('pickup_min_minutes')
        b.drop_column('eta_min_minutes')
