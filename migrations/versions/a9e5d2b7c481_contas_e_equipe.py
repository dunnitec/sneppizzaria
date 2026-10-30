"""contas e equipe: gastos, funcionários, dias trabalhados e pagamento do motoboy

Revision ID: a9e5d2b7c481
Revises: f2c6a8e4b190
Create Date: 2026-10-30 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a9e5d2b7c481'
down_revision = 'f2c6a8e4b190'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('couriers') as b:
        b.add_column(sa.Column('pay_mode', sa.String(length=16), nullable=False, server_default='taxa'))
        b.add_column(sa.Column('pay_per_delivery', sa.Numeric(8, 2), nullable=True))
        b.add_column(sa.Column('pay_daily', sa.Numeric(8, 2), nullable=True))
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('role', sa.String(length=60), nullable=True),
        sa.Column('pay_type', sa.String(length=10), nullable=False),
        sa.Column('pay_amount', sa.Numeric(8, 2), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'work_days',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.UniqueConstraint('employee_id', 'day', name='uq_work_days_employee_day'),
    )
    op.create_index('ix_work_days_employee_id', 'work_days', ['employee_id'])
    op.create_table(
        'expenses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('description', sa.String(length=160), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('courier_id', sa.Integer(), sa.ForeignKey('couriers.id'), nullable=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=True),
        sa.Column('is_advance', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_expenses_tenant_id', 'expenses', ['tenant_id'])
    op.create_index('ix_expenses_day', 'expenses', ['day'])


def downgrade():
    op.drop_index('ix_expenses_day', 'expenses')
    op.drop_index('ix_expenses_tenant_id', 'expenses')
    op.drop_table('expenses')
    op.drop_index('ix_work_days_employee_id', 'work_days')
    op.drop_table('work_days')
    op.drop_table('employees')
    with op.batch_alter_table('couriers') as b:
        b.drop_column('pay_daily')
        b.drop_column('pay_per_delivery')
        b.drop_column('pay_mode')
