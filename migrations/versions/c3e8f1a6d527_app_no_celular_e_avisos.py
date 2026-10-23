"""app no celular (PWA) e avisos (Web Push)

Revision ID: c3e8f1a6d527
Revises: b7d1e5a9c204
Create Date: 2026-10-24 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e8f1a6d527'
down_revision = 'b7d1e5a9c204'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('app_icon', sa.String(length=255), nullable=True))
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('endpoint', sa.String(length=600), nullable=False),
        sa.Column('p256dh', sa.String(length=200), nullable=False),
        sa.Column('auth', sa.String(length=80), nullable=False),
        sa.Column('wants_promos', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name='fk_push_subscriptions_customer_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_push_subscriptions_tenant_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    op.create_index('ix_push_subscriptions_customer_id', 'push_subscriptions', ['customer_id'], unique=False)
    op.create_table(
        'push_campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=60), nullable=False),
        sa.Column('body', sa.String(length=160), nullable=False),
        sa.Column('url', sa.String(length=200), nullable=True),
        sa.Column('audience', sa.String(length=20), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('repeat_weekly', sa.Boolean(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('sent_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name='fk_push_campaigns_tenant_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_push_campaigns_scheduled_at', 'push_campaigns', ['scheduled_at'], unique=False)


def downgrade():
    op.drop_index('ix_push_campaigns_scheduled_at', table_name='push_campaigns')
    op.drop_table('push_campaigns')
    op.drop_index('ix_push_subscriptions_customer_id', table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_column('app_icon')
