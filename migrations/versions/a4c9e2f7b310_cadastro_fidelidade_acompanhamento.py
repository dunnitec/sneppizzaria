"""cadastro do cliente, fidelidade, desconto do 1º pedido e acompanhamento do pedido

Revision ID: a4c9e2f7b310
Revises: f2b8d4c6a1e3
Create Date: 2026-10-23 09:00:00

"""
import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4c9e2f7b310'
down_revision = 'f2b8d4c6a1e3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loyalty_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('loyalty_goal', sa.Integer(), server_default='8', nullable=False))
        batch_op.add_column(sa.Column('loyalty_kinds', sa.String(length=40), server_default='pizza,doce', nullable=False))
        batch_op.add_column(sa.Column('loyalty_reward_category_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('loyalty_reward_size', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('first_order_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('first_order_type', sa.String(length=10), server_default='percent', nullable=False))
        batch_op.add_column(sa.Column('first_order_value', sa.Numeric(precision=8, scale=2), server_default='10', nullable=False))

    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pin_hash', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('registered_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confirmed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('track_token', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('discount', sa.Numeric(precision=8, scale=2), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('discount_note', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('first_order', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('loyalty_reward', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_index('ix_orders_track_token', ['track_token'], unique=True)

    # pedidos que já existem ganham o link de acompanhamento
    conn = op.get_bind()
    for (oid,) in conn.execute(sa.text("SELECT id FROM orders")).fetchall():
        conn.execute(sa.text("UPDATE orders SET track_token = :t WHERE id = :i"), {"t": secrets.token_urlsafe(16), "i": oid})


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_index('ix_orders_track_token')
        for col in ('loyalty_reward', 'first_order', 'discount_note', 'discount', 'track_token', 'confirmed_at'):
            batch_op.drop_column(col)
    with op.batch_alter_table('customers', schema=None) as batch_op:
        for col in ('locked_until', 'failed_attempts', 'registered_at', 'pin_hash'):
            batch_op.drop_column(col)
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        for col in ('first_order_value', 'first_order_type', 'first_order_enabled', 'loyalty_reward_size',
                    'loyalty_reward_category_id', 'loyalty_kinds', 'loyalty_goal', 'loyalty_enabled'):
            batch_op.drop_column(col)
