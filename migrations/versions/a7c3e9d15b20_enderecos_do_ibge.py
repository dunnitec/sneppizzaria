"""endereços do IBGE: local exato de cada número da rua para o frete por distância

Revision ID: a7c3e9d15b20
Revises: d4f7a2c8e615
Create Date: 2026-11-04 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c3e9d15b20'
down_revision = 'd4f7a2c8e615'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('address_points',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('city', sa.String(length=80), nullable=False),
                    sa.Column('uf', sa.String(length=2), nullable=False),
                    sa.Column('street_key', sa.String(length=120), nullable=False),
                    sa.Column('number', sa.Integer(), nullable=False),
                    sa.Column('cep', sa.String(length=8), nullable=True),
                    sa.Column('lat', sa.Float(), nullable=False),
                    sa.Column('lng', sa.Float(), nullable=False),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_address_points_street', 'address_points', ['city', 'uf', 'street_key', 'number'])


def downgrade():
    op.drop_index('ix_address_points_street', table_name='address_points')
    op.drop_table('address_points')
