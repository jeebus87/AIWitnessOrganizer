"""Add content_hash to documents for caching

Revision ID: 015
Revises: 014
Create Date: 2026-01-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add content_hash column to documents table for content caching
    op.add_column('documents', sa.Column('content_hash', sa.String(64), nullable=True))
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])


def downgrade() -> None:
    op.drop_index('ix_documents_content_hash', table_name='documents')
    op.drop_column('documents', 'content_hash')
