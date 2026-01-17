"""Add is_archived and archived_at columns to processing_jobs

Revision ID: 010
Revises: 009
Create Date: 2026-01-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_archived column with default False
    op.add_column(
        'processing_jobs',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add archived_at timestamp column
    op.add_column(
        'processing_jobs',
        sa.Column('archived_at', sa.DateTime(), nullable=True)
    )

    # Add index for faster queries on archived status
    op.create_index('ix_processing_jobs_is_archived', 'processing_jobs', ['is_archived'])


def downgrade() -> None:
    op.drop_index('ix_processing_jobs_is_archived', table_name='processing_jobs')
    op.drop_column('processing_jobs', 'archived_at')
    op.drop_column('processing_jobs', 'is_archived')
