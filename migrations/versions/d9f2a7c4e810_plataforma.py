"""plataforma: plano e situação da loja, administradores da plataforma

Revision ID: d9f2a7c4e810
Revises: c3e8f1a6d527
Create Date: 2026-10-27 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd9f2a7c4e810'
down_revision = 'c3e8f1a6d527'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plan', sa.String(length=20), nullable=False, server_default='completo'))
        batch_op.add_column(sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('platform_notes', sa.Text(), nullable=True))
    op.create_table(
        'platform_admins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('failed_attempts', sa.Integer(), nullable=False),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )


def downgrade():
    op.drop_table('platform_admins')
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_column('platform_notes')
        batch_op.drop_column('active')
        batch_op.drop_column('plan')
