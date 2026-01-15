"""Initial schema with all models

Revision ID: 001_initial
Revises:
Create Date: 2026-01-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('firebase_uid', sa.String(128), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('subscription_tier', sa.Enum('free', 'basic', 'professional', 'enterprise', name='subscriptiontier'), nullable=False),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_firebase_uid', 'users', ['firebase_uid'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Create clio_integrations table
    op.create_table(
        'clio_integrations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(), nullable=False),
        sa.Column('clio_user_id', sa.String(128), nullable=True),
        sa.Column('clio_account_id', sa.String(128), nullable=True),
        sa.Column('clio_region', sa.String(10), nullable=False, default='us'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_clio_integrations_id', 'clio_integrations', ['id'])

    # Create matters table
    op.create_table(
        'matters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('clio_matter_id', sa.String(128), nullable=False),
        sa.Column('display_number', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('practice_area', sa.String(255), nullable=True),
        sa.Column('client_name', sa.String(255), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_matters_id', 'matters', ['id'])
    op.create_index('ix_matters_clio_matter_id', 'matters', ['clio_matter_id'])
    op.create_index('ix_matters_user_clio', 'matters', ['user_id', 'clio_matter_id'], unique=True)

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('matter_id', sa.Integer(), nullable=False),
        sa.Column('clio_document_id', sa.String(128), nullable=True),
        sa.Column('parent_document_id', sa.Integer(), nullable=True),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('etag', sa.String(255), nullable=True),
        sa.Column('is_processed', sa.Boolean(), nullable=False, default=False),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('analysis_cache', sa.JSON(), nullable=True),
        sa.Column('analysis_cache_key', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documents_id', 'documents', ['id'])
    op.create_index('ix_documents_clio_document_id', 'documents', ['clio_document_id'])

    # Create witnesses table
    op.create_table(
        'witnesses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('plaintiff', 'defendant', 'eyewitness', 'expert', 'attorney', 'physician', 'police_officer', 'family_member', 'colleague', 'bystander', 'mentioned', 'other', name='witnessrole'), nullable=False),
        sa.Column('importance', sa.Enum('high', 'medium', 'low', name='importancelevel'), nullable=False),
        sa.Column('observation', sa.Text(), nullable=True),
        sa.Column('source_quote', sa.Text(), nullable=True),
        sa.Column('context', sa.Text(), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_witnesses_id', 'witnesses', ['id'])
    op.create_index('ix_witnesses_full_name', 'witnesses', ['full_name'])

    # Create processing_jobs table
    op.create_table(
        'processing_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('celery_task_id', sa.String(255), nullable=True),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('target_matter_id', sa.Integer(), nullable=True),
        sa.Column('search_witnesses', sa.JSON(), nullable=True),
        sa.Column('include_archived', sa.Boolean(), nullable=False, default=False),
        sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', 'cancelled', name='jobstatus'), nullable=False),
        sa.Column('total_documents', sa.Integer(), nullable=False, default=0),
        sa.Column('processed_documents', sa.Integer(), nullable=False, default=0),
        sa.Column('failed_documents', sa.Integer(), nullable=False, default=0),
        sa.Column('total_witnesses_found', sa.Integer(), nullable=False, default=0),
        sa.Column('result_summary', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_matter_id'], ['matters.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_processing_jobs_id', 'processing_jobs', ['id'])
    op.create_index('ix_processing_jobs_celery_task_id', 'processing_jobs', ['celery_task_id'])


def downgrade() -> None:
    op.drop_table('processing_jobs')
    op.drop_table('witnesses')
    op.drop_table('documents')
    op.drop_table('matters')
    op.drop_table('clio_integrations')
    op.drop_table('users')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS importancelevel")
    op.execute("DROP TYPE IF EXISTS witnessrole")
    op.execute("DROP TYPE IF EXISTS subscriptiontier")
