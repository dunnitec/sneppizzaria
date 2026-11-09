"""combo do dia: dias da semana em que o item vale

Revision ID: e6b2a4c8d1f3
Revises: d5a1f3b7c9e2
Create Date: 2026-11-09 11:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6b2a4c8d1f3'
down_revision = 'd5a1f3b7c9e2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products') as b:
        b.add_column(sa.Column('daily_days', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('products') as b:
        b.drop_column('daily_days')
