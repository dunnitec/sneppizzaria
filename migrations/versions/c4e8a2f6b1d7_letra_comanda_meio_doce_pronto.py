"""letra do cupom, comanda do motoboy opcional, meio a meio com doce e aviso de pronto

Revision ID: c4e8a2f6b1d7
Revises: b3d9f1a7c2e4
Create Date: 2026-11-07 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e8a2f6b1d7'
down_revision = 'b3d9f1a7c2e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('print_dispatch', sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column('receipt_font', sa.Integer(), nullable=False, server_default='100'))
    with op.batch_alter_table('categories') as b:
        b.add_column(sa.Column('mix_sources', sa.Text(), nullable=True))
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('ready_at', sa.DateTime(), nullable=True))
    # Premium já sai podendo ser meio a meio com as Doces (ex.: 1/2 Frango 1/2 Oreo), onde as duas linhas existem
    op.execute("""UPDATE categories SET mix_sources = '["doces"]'
                  WHERE slug = 'premium' AND kind = 'pizza' AND tenant_id IN
                  (SELECT tenant_id FROM categories WHERE slug = 'doces' AND kind = 'doce')""")


def downgrade():
    with op.batch_alter_table('orders') as b:
        b.drop_column('ready_at')
    with op.batch_alter_table('categories') as b:
        b.drop_column('mix_sources')
    with op.batch_alter_table('tenants') as b:
        b.drop_column('receipt_font')
        b.drop_column('print_dispatch')
