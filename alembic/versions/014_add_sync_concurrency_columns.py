"""Add sync concurrency columns

Revision ID: 014
Revises: 013
Create Date: 2026-01-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sync_status enum type
    op.execute("CREATE TYPE syncstatus AS ENUM ('idle', 'syncing', 'failed')")

    # Add sync_status to matters table
    op.add_column('matters', sa.Column('sync_status', sa.Enum('idle', 'syncing', 'failed', name='syncstatus'), nullable=False, server_default='idle'))

    # Add is_soft_deleted to documents table
    op.add_column('documents', sa.Column('is_soft_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('ix_documents_is_soft_deleted', 'documents', ['is_soft_deleted'])

    # Add document_ids_snapshot to processing_jobs table
    op.add_column('processing_jobs', sa.Column('document_ids_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('processing_jobs', 'document_ids_snapshot')
    op.drop_index('ix_documents_is_soft_deleted', table_name='documents')
    op.drop_column('documents', 'is_soft_deleted')
    op.drop_column('matters', 'sync_status')
    op.execute("DROP TYPE syncstatus")
