"""tipo de loja (pizzaria, lanchonete, açaí...) e complementos do “monte o seu”

Revision ID: c5a8e1f3b742
Revises: b3e7c9a1d528
Create Date: 2026-10-30 21:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5a8e1f3b742'
down_revision = 'b3e7c9a1d528'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants') as b:
        b.add_column(sa.Column('business_type', sa.String(length=20), nullable=False, server_default='pizzaria'))
    with op.batch_alter_table('categories') as b:
        b.add_column(sa.Column('pick_label', sa.String(length=60), nullable=True))
        b.add_column(sa.Column('pick_options', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('categories') as b:
        b.drop_column('pick_options')
        b.drop_column('pick_label')
    with op.batch_alter_table('tenants') as b:
        b.drop_column('business_type')
