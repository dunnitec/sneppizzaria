"""cupom de entrega gratis

Revision ID: b3e7f1a9c2d4
Revises: a8d4c6e0f3b5
Create Date: 2026-11-13 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3e7f1a9c2d4'
down_revision = 'a8d4c6e0f3b5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('coupons') as b:
        b.add_column(sa.Column('max_km', sa.Numeric(6, 1), nullable=True))


def downgrade():
    with op.batch_alter_table('coupons') as b:
        b.drop_column('max_km')
