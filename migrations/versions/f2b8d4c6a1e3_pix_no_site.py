"""pix no site: chave da loja e confirmação do pagamento no pedido

Revision ID: f2b8d4c6a1e3
Revises: e7a3c51b9f20
Create Date: 2026-10-22 14:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b8d4c6a1e3'
down_revision = 'e7a3c51b9f20'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pix_key', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('pix_key_type', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('pix_name', sa.String(length=25), nullable=True))
        batch_op.add_column(sa.Column('pix_city', sa.String(length=15), nullable=True))
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pix_paid_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('pix_paid_at')
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_column('pix_city')
        batch_op.drop_column('pix_name')
        batch_op.drop_column('pix_key_type')
        batch_op.drop_column('pix_key')
