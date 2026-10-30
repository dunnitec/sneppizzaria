"""custos dos produtos, taxas da maquininha e custo do item na venda (relatório de lucro)

Revision ID: b3e7c9a1d528
Revises: a9e5d2b7c481
Create Date: 2026-10-30 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3e7c9a1d528'
down_revision = 'a9e5d2b7c481'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('categories') as b:
        b.add_column(sa.Column('cost_percent', sa.Numeric(5, 2), nullable=True))
    with op.batch_alter_table('product_variants') as b:
        b.add_column(sa.Column('cost', sa.Numeric(8, 2), nullable=True))
    with op.batch_alter_table('borders') as b:
        b.add_column(sa.Column('cost', sa.Numeric(8, 2), nullable=True))
    with op.batch_alter_table('order_items') as b:
        b.add_column(sa.Column('unit_cost', sa.Numeric(8, 2), nullable=True))
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('payment_fees', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('tenants') as b:
        b.drop_column('payment_fees')
    with op.batch_alter_table('order_items') as b:
        b.drop_column('unit_cost')
    with op.batch_alter_table('borders') as b:
        b.drop_column('cost')
    with op.batch_alter_table('product_variants') as b:
        b.drop_column('cost')
    with op.batch_alter_table('categories') as b:
        b.drop_column('cost_percent')
