"""Add job_number column and organization_job_counters table

Revision ID: 007
Revises: 006
Create Date: 2025-01-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add job_number column to processing_jobs
    op.add_column('processing_jobs', sa.Column('job_number', sa.Integer(), nullable=True))
    op.create_index('ix_processing_jobs_job_number', 'processing_jobs', ['job_number'])

    # Create organization_job_counters table if it doesn't exist
    op.create_table(
        'organization_job_counters',
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('job_counter', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('organization_id')
    )


def downgrade() -> None:
    op.drop_table('organization_job_counters')
    op.drop_index('ix_processing_jobs_job_number', table_name='processing_jobs')
    op.drop_column('processing_jobs', 'job_number')
