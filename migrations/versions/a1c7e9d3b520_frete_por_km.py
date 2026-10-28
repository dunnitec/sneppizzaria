"""frete por distância (km) e entrega "a combinar" marcada no pedido

Revision ID: a1c7e9d3b520
Revises: d9f2a7c4e810
Create Date: 2026-10-28 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c7e9d3b520'
down_revision = 'd9f2a7c4e810'  # no hub: e4b8c2d6f913 (planos editáveis)
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('delivery_mode', sa.String(length=10), nullable=False, server_default='bairro'))
        b.add_column(sa.Column('store_lat', sa.Float(), nullable=True))
        b.add_column(sa.Column('store_lng', sa.Float(), nullable=True))
        b.add_column(sa.Column('store_city', sa.String(length=80), nullable=True))
        b.add_column(sa.Column('store_uf', sa.String(length=2), nullable=True))
        b.add_column(sa.Column('km_price', sa.Numeric(8, 2), nullable=True))
        b.add_column(sa.Column('km_base_km', sa.Numeric(6, 1), nullable=True))
        b.add_column(sa.Column('km_base_fee', sa.Numeric(8, 2), nullable=True))
        b.add_column(sa.Column('km_max', sa.Numeric(6, 1), nullable=True))
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('cep', sa.String(length=8), nullable=True))
        b.add_column(sa.Column('distance_km', sa.Numeric(6, 1), nullable=True))
        b.add_column(sa.Column('fee_pending', sa.Boolean(), nullable=False, server_default=sa.false()))
    # até aqui a entrega "a combinar" era reconhecida pelo nome do bairro
    op.execute(sa.text("UPDATE orders SET fee_pending = :yes WHERE neighborhood_name = '(outro bairro)'")
               .bindparams(yes=True))
    op.create_table(
        'geo_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lng', sa.Float(), nullable=True),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('city', sa.String(length=80), nullable=True),
        sa.Column('uf', sa.String(length=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )


def downgrade():
    op.drop_table('geo_cache')
    with op.batch_alter_table('orders') as b:
        b.drop_column('fee_pending')
        b.drop_column('distance_km')
        b.drop_column('cep')
    with op.batch_alter_table('tenants') as b:
        for col in ('km_max', 'km_base_fee', 'km_base_km', 'km_price', 'store_uf', 'store_city', 'store_lng', 'store_lat', 'delivery_mode'):
            b.drop_column(col)
