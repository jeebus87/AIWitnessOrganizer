"""Add firm_documents table and firm_document_id to witnesses

Revision ID: 025
Revises: 024
Create Date: 2025-01-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade():
    # Create firm_documents table (shared with AIDiscoveryDrafter)
    op.create_table(
        'firm_documents',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, index=True),

        # Clio references
        sa.Column('clio_document_id', sa.String(255), nullable=False, index=True),
        sa.Column('clio_matter_id', sa.String(255), nullable=True, index=True),
        sa.Column('clio_folder_path', sa.String(1000), nullable=True),

        # File metadata
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('content_type', sa.String(100), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False),

        # Parsed content
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('extraction_method', sa.String(255), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),

        # Hybrid PDF processing metadata
        sa.Column('pages_with_text', sa.Integer(), nullable=True),
        sa.Column('pages_with_ocr', sa.Integer(), nullable=True),

        # AI analysis
        sa.Column('document_summary', sa.Text(), nullable=True),
        sa.Column('document_type', sa.String(100), nullable=True),

        # Timestamps from Clio
        sa.Column('clio_created_at', sa.DateTime(), nullable=True),
        sa.Column('clio_updated_at', sa.DateTime(), nullable=True),

        # Our timestamps
        sa.Column('parsed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # Add firm_document_id column to witnesses table
    op.add_column(
        'witnesses',
        sa.Column('firm_document_id', sa.Integer(), nullable=True)
    )

    # Add index for the new column
    op.create_index('ix_witnesses_firm_document_id', 'witnesses', ['firm_document_id'])

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_witnesses_firm_document_id',
        'witnesses', 'firm_documents',
        ['firm_document_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    # Drop foreign key constraint
    op.drop_constraint('fk_witnesses_firm_document_id', 'witnesses', type_='foreignkey')

    # Drop index
    op.drop_index('ix_witnesses_firm_document_id', 'witnesses')

    # Drop column from witnesses
    op.drop_column('witnesses', 'firm_document_id')

    # Drop firm_documents table
    op.drop_table('firm_documents')
