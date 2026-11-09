"""cupons de desconto

Revision ID: f7c3b5d9e2a4
Revises: e6b2a4c8d1f3
Create Date: 2026-11-09 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f7c3b5d9e2a4'
down_revision = 'e6b2a4c8d1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'coupons',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', name='fk_coupons_tenant_id'), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=60), nullable=True),
        sa.Column('discount_type', sa.String(length=10), nullable=False),
        sa.Column('value', sa.Numeric(8, 2), nullable=False),
        sa.Column('min_order', sa.Numeric(8, 2), nullable=True),
        sa.Column('starts_on', sa.Date(), nullable=True),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('per_customer', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('show_on_site', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_coupons_tenant_code'),
    )
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('coupon_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('coupon_code', sa.String(length=20), nullable=True))
        b.create_index('ix_orders_coupon_id', ['coupon_id'])


def downgrade():
    with op.batch_alter_table('orders') as b:
        b.drop_index('ix_orders_coupon_id')
        b.drop_column('coupon_code')
        b.drop_column('coupon_id')
    op.drop_table('coupons')
