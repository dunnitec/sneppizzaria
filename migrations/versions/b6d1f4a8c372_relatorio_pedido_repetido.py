"""relatório 26/10: código do envio no pedido (sem pedido repetido) e tamanho nas promoções de preço fixo

Revision ID: b6d1f4a8c372
Revises: a1c7e9d3b520
Create Date: 2026-10-29 12:00:00

"""
import json

from alembic import op
import sqlalchemy as sa


revision = 'b6d1f4a8c372'
down_revision = 'a1c7e9d3b520'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('client_ref', sa.String(length=40), nullable=True))
        b.create_unique_constraint('uq_orders_client_ref', ['tenant_id', 'client_ref'])
    # promoção de preço fixo em categoria de um tamanho só, gravada sem o tamanho: passa a valer só
    # para esse tamanho (um tamanho criado depois, mais caro, entraria no mesmo preço)
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT p.id, c.sizes_json FROM promotions p JOIN categories c ON c.id = p.category_id "
        "WHERE p.discount_type = 'price' AND (p.size_label IS NULL OR p.size_label = '')")).fetchall()
    for promo_id, sizes_json in rows:
        sizes = json.loads(sizes_json) if sizes_json else []
        if len(sizes) == 1:
            conn.execute(sa.text("UPDATE promotions SET size_label = :s WHERE id = :i"),
                         {"s": sizes[0]["label"], "i": promo_id})


def downgrade():
    with op.batch_alter_table('orders') as b:
        b.drop_constraint('uq_orders_client_ref', type_='unique')
        b.drop_column('client_ref')
