"""dividir a conta entre pessoas

Revision ID: d3a9b7e2c614
Revises: c8e2f5a1d947
Create Date: 2026-10-29 19:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd3a9b7e2c614'
down_revision = 'c8e2f5a1d947'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders') as b:
        b.add_column(sa.Column('split_people', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('orders') as b:
        b.drop_column('split_people')
