"""Add clio_folder_id to documents table

Revision ID: 013
Revises: 012
Create Date: 2024-01-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add clio_folder_id column to documents table
    op.add_column('documents', sa.Column('clio_folder_id', sa.String(128), nullable=True))

    # Add index for faster folder-based queries
    op.create_index('ix_documents_clio_folder_id', 'documents', ['clio_folder_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_clio_folder_id', table_name='documents')
    op.drop_column('documents', 'clio_folder_id')
