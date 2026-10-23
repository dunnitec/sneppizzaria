"""fidelidade com vários cartões (ex.: Promocional e Premium) e sabores do prêmio

Revision ID: b7d1e5a9c204
Revises: a4c9e2f7b310
Create Date: 2026-10-23 15:00:00

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d1e5a9c204'
down_revision = 'a4c9e2f7b310'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'loyalty_programs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('goal', sa.Integer(), nullable=False),
        sa.Column('count_category_ids', sa.Text(), nullable=True),
        sa.Column('reward_category_id', sa.Integer(), nullable=True),
        sa.Column('reward_size', sa.String(length=60), nullable=True),
        sa.Column('reward_product_ids', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['reward_category_id'], ['categories.id'], name='fk_loyalty_programs_reward_category'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_loyalty_programs_tenant_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_order_items_category_id', ['category_id'], unique=False)
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loyalty_programs', sa.String(length=80), nullable=True))

    conn = op.get_bind()
    # itens antigos: acha a categoria pelo nome guardado na venda
    conn.execute(sa.text(
        "UPDATE order_items SET category_id = (SELECT c.id FROM categories c JOIN orders o ON o.tenant_id = c.tenant_id "
        "WHERE o.id = order_items.order_id AND c.name = order_items.category_name LIMIT 1)"))
    # o cartão único antigo (Tenant.loyalty_*) vira o primeiro cartão
    tenants = conn.execute(sa.text(
        "SELECT id, loyalty_enabled, loyalty_goal, loyalty_kinds, loyalty_reward_category_id, loyalty_reward_size "
        "FROM tenants WHERE loyalty_reward_category_id IS NOT NULL")).fetchall()
    for tid, enabled, goal, kinds, reward_cat, size in tenants:
        kinds = [k for k in (kinds or "").split(",") if k]
        counted = [r[0] for r in conn.execute(sa.text("SELECT id, kind FROM categories WHERE tenant_id = :t"), {"t": tid})
                   if r[1] in kinds]
        name = conn.execute(sa.text("SELECT name FROM categories WHERE id = :c"), {"c": reward_cat}).scalar() or "Fidelidade"
        products = [r[0] for r in conn.execute(sa.text("SELECT id FROM products WHERE category_id = :c"), {"c": reward_cat})]
        conn.execute(sa.text(
            "INSERT INTO loyalty_programs (tenant_id, name, active, goal, count_category_ids, reward_category_id, reward_size, "
            "reward_product_ids, sort_order) VALUES (:t, :n, :a, :g, :cc, :rc, :rs, :rp, 0)"),
            {"t": tid, "n": name.replace("Pizzas ", "").replace("Pizza ", "")[:40], "a": bool(enabled), "g": goal or 10,
             "cc": json.dumps(counted), "rc": reward_cat, "rs": size, "rp": json.dumps(products)})
        pid = conn.execute(sa.text("SELECT max(id) FROM loyalty_programs WHERE tenant_id = :t"), {"t": tid}).scalar()
        conn.execute(sa.text("UPDATE orders SET loyalty_programs = :p WHERE tenant_id = :t AND loyalty_reward"),
                     {"p": f",{pid},", "t": tid})


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('loyalty_programs')
    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.drop_index('ix_order_items_category_id')
        batch_op.drop_column('category_id')
    op.drop_table('loyalty_programs')
