"""Add organizations, billing, and relevance scoring

Revision ID: 005
Revises: 004_add_source_page
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_organizations_billing'
down_revision: Union[str, None] = '004_add_source_page'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('clio_account_id', sa.String(128), nullable=True),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('subscription_status', sa.String(50), nullable=False, server_default='free'),
        sa.Column('subscription_tier', sa.String(50), nullable=False, server_default='free'),
        sa.Column('user_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('bonus_credits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_organizations_id', 'organizations', ['id'])
    op.create_index('ix_organizations_clio_account_id', 'organizations', ['clio_account_id'], unique=True)
    op.create_index('ix_organizations_stripe_customer_id', 'organizations', ['stripe_customer_id'], unique=True)
    op.create_index('ix_organizations_stripe_subscription_id', 'organizations', ['stripe_subscription_id'], unique=True)

    # Create organization_job_counters table
    op.create_table(
        'organization_job_counters',
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('job_counter', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('organization_id')
    )

    # Add organization fields to users table
    op.add_column('users', sa.Column('organization_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))
    op.create_foreign_key(
        'fk_users_organization_id',
        'users', 'organizations',
        ['organization_id'], ['id']
    )
    op.create_index('ix_users_organization_id', 'users', ['organization_id'])

    # Add relevance columns to witnesses table
    op.add_column(
        'witnesses',
        sa.Column('relevance', sa.Enum(
            'highly_relevant', 'relevant', 'somewhat_relevant', 'not_relevant',
            name='relevancelevel'
        ), nullable=True, server_default='relevant')
    )
    op.add_column('witnesses', sa.Column('relevance_reason', sa.Text(), nullable=True))

    # Create report_credit_usage table
    op.create_table(
        'report_credit_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('credits_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_report_credit_usage_id', 'report_credit_usage', ['id'])
    op.create_index('ix_report_credit_usage_date', 'report_credit_usage', ['date'])
    op.create_index('ix_credit_usage_user_date', 'report_credit_usage', ['user_id', 'date'], unique=True)

    # Create credit_purchases table
    op.create_table(
        'credit_purchases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('purchased_by_user_id', sa.Integer(), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.String(255), nullable=True),
        sa.Column('credits_purchased', sa.Integer(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['purchased_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_credit_purchases_id', 'credit_purchases', ['id'])
    op.create_index('ix_credit_purchases_stripe_payment', 'credit_purchases', ['stripe_payment_intent_id'], unique=True)


def downgrade() -> None:
    # Drop credit_purchases table
    op.drop_index('ix_credit_purchases_stripe_payment', 'credit_purchases')
    op.drop_index('ix_credit_purchases_id', 'credit_purchases')
    op.drop_table('credit_purchases')

    # Drop report_credit_usage table
    op.drop_index('ix_credit_usage_user_date', 'report_credit_usage')
    op.drop_index('ix_report_credit_usage_date', 'report_credit_usage')
    op.drop_index('ix_report_credit_usage_id', 'report_credit_usage')
    op.drop_table('report_credit_usage')

    # Remove relevance columns from witnesses
    op.drop_column('witnesses', 'relevance_reason')
    op.drop_column('witnesses', 'relevance')
    op.execute('DROP TYPE IF EXISTS relevancelevel')

    # Remove organization fields from users
    op.drop_index('ix_users_organization_id', 'users')
    op.drop_constraint('fk_users_organization_id', 'users', type_='foreignkey')
    op.drop_column('users', 'is_admin')
    op.drop_column('users', 'organization_id')

    # Drop organization_job_counters table
    op.drop_table('organization_job_counters')

    # Drop organizations table
    op.drop_index('ix_organizations_stripe_subscription_id', 'organizations')
    op.drop_index('ix_organizations_stripe_customer_id', 'organizations')
    op.drop_index('ix_organizations_clio_account_id', 'organizations')
    op.drop_index('ix_organizations_id', 'organizations')
    op.drop_table('organizations')
