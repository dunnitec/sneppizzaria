"""número do pedido volta a 1 todo dia (antes era todo mês)

Os pedidos antigos ficam como estão (chave "2026-11" e o número que já foi impresso);
os novos usam a data do expediente ("2026-11-06"), então não há como repetir número.

Revision ID: b3d9f1a7c2e4
Revises: a7c3e9d15b20
Create Date: 2026-11-06 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3d9f1a7c2e4'
down_revision = 'a7c3e9d15b20'
branch_labels = None
depends_on = None


def upgrade():
    uniques = {u['name'] for u in sa.inspect(op.get_bind()).get_unique_constraints('orders')}
    with op.batch_alter_table('orders') as b:
        if 'uq_orders_ticket' in uniques:  # some quando a migração foi desfeita
            b.drop_constraint('uq_orders_ticket', type_='unique')
        b.alter_column('ticket_month', new_column_name='ticket_day', existing_type=sa.String(length=7),
                       type_=sa.String(length=10))
    # em outro passo: no mesmo lote do SQLite a trava nova com a coluna renomeada se perde
    with op.batch_alter_table('orders') as b:
        b.create_unique_constraint('uq_orders_ticket', ['tenant_id', 'ticket_day', 'ticket_number'])


def downgrade():
    # volta para o mês sem a trava de número único: os pedidos feitos por dia repetem número no mês.
    with op.batch_alter_table('orders') as b:
        b.drop_constraint('uq_orders_ticket', type_='unique')
    op.execute("UPDATE orders SET ticket_day = substr(ticket_day, 1, 7)")
    with op.batch_alter_table('orders') as b:
        b.alter_column('ticket_day', new_column_name='ticket_month', existing_type=sa.String(length=10),
                       type_=sa.String(length=7))
