"""item sem borda (calzone)

Revision ID: c8e2f5a1d947
Revises: b6d1f4a8c372
Create Date: 2026-10-29 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8e2f5a1d947'
down_revision = 'b6d1f4a8c372'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products') as b:
        b.add_column(sa.Column('accepts_border', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('products') as b:
        b.drop_column('accepts_border')
