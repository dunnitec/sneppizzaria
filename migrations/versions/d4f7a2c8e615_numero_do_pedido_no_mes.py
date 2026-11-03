"""número do pedido que volta a 1 todo mês

Revision ID: d4f7a2c8e615
Revises: c5a8e1f3b742
Create Date: 2026-11-03 12:00:00

"""
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision = 'd4f7a2c8e615'
down_revision = 'c5a8e1f3b742'
branch_labels = None
depends_on = None

UTC, STORE_TZ = ZoneInfo("UTC"), ZoneInfo("America/Sao_Paulo")


def upgrade():
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('ticket_month', sa.String(length=7), nullable=True))
        b.add_column(sa.Column('ticket_number', sa.Integer(), nullable=True))
    # pedidos antigos ganham o número que teriam tido, mês a mês
    orders = sa.table('orders', sa.column('id', sa.Integer), sa.column('tenant_id', sa.Integer),
                      sa.column('created_at', sa.DateTime), sa.column('ticket_month', sa.String),
                      sa.column('ticket_number', sa.Integer))
    bind = op.get_bind()
    counters = {}
    rows = bind.execute(sa.select(orders.c.id, orders.c.tenant_id, orders.c.created_at).order_by(orders.c.id)).all()
    for row in rows:
        if not row.created_at:
            continue  # sem data: continua mostrando o id
        month = row.created_at.replace(tzinfo=UTC).astimezone(STORE_TZ).strftime("%Y-%m")
        key = (row.tenant_id, month)
        counters[key] = counters.get(key, 0) + 1
        bind.execute(orders.update().where(orders.c.id == row.id).values(ticket_month=month, ticket_number=counters[key]))
    with op.batch_alter_table('orders') as b:
        b.create_unique_constraint('uq_orders_ticket', ['tenant_id', 'ticket_month', 'ticket_number'])


def downgrade():
    with op.batch_alter_table('orders') as b:
        b.drop_constraint('uq_orders_ticket', type_='unique')
        b.drop_column('ticket_number')
        b.drop_column('ticket_month')
