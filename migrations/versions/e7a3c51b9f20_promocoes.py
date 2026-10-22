"""promoções: descontos do painel e nome da promoção no item do pedido

Revision ID: e7a3c51b9f20
Revises: d1f54ee367c8
Create Date: 2026-10-22 09:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7a3c51b9f20'
down_revision = 'd1f54ee367c8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'promotions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('message', sa.String(length=200), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('product_ids', sa.Text(), nullable=True),
        sa.Column('size_label', sa.String(length=60), nullable=True),
        sa.Column('discount_type', sa.String(length=10), nullable=False),
        sa.Column('value', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('weekdays', sa.String(length=20), nullable=True),
        sa.Column('starts_on', sa.Date(), nullable=True),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('show_popup', sa.Boolean(), nullable=False),
        sa.Column('image', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name='fk_promotions_category_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_promotions_tenant_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('promo_name', sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.drop_column('promo_name')
    op.drop_table('promotions')
