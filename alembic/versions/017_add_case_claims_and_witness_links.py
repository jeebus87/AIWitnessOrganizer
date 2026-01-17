"""Add case claims and witness links for relevancy system

Revision ID: 017
Revises: 016
Create Date: 2026-01-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create claim_type enum
    op.execute("CREATE TYPE claimtype AS ENUM ('allegation', 'defense')")

    # Create case_claims table
    op.create_table(
        'case_claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('matter_id', sa.Integer(), nullable=False),
        sa.Column('claim_type', sa.Enum('allegation', 'defense', name='claimtype'), nullable=False),
        sa.Column('claim_number', sa.Integer(), nullable=False),
        sa.Column('claim_text', sa.Text(), nullable=False),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('source_page', sa.Integer(), nullable=True),
        sa.Column('extraction_method', sa.String(20), nullable=False, server_default='discovery'),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_case_claims_id', 'case_claims', ['id'])
    op.create_index('ix_case_claims_matter_id', 'case_claims', ['matter_id'])
    # Unique constraint: one claim number per type per matter
    op.create_index(
        'ix_case_claims_matter_type_number',
        'case_claims',
        ['matter_id', 'claim_type', 'claim_number'],
        unique=True
    )

    # Create witness_claim_links table
    op.create_table(
        'witness_claim_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('witness_id', sa.Integer(), nullable=False),
        sa.Column('case_claim_id', sa.Integer(), nullable=False),
        sa.Column('relevance_explanation', sa.Text(), nullable=True),
        sa.Column('supports_or_undermines', sa.String(20), nullable=False, server_default='neutral'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['witness_id'], ['witnesses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['case_claim_id'], ['case_claims.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_witness_claim_links_id', 'witness_claim_links', ['id'])
    op.create_index('ix_witness_claim_links_witness_id', 'witness_claim_links', ['witness_id'])
    op.create_index('ix_witness_claim_links_case_claim_id', 'witness_claim_links', ['case_claim_id'])
    # Unique constraint: one link per witness per claim
    op.create_index(
        'ix_witness_claim_links_unique',
        'witness_claim_links',
        ['witness_id', 'case_claim_id'],
        unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_witness_claim_links_unique', table_name='witness_claim_links')
    op.drop_index('ix_witness_claim_links_case_claim_id', table_name='witness_claim_links')
    op.drop_index('ix_witness_claim_links_witness_id', table_name='witness_claim_links')
    op.drop_index('ix_witness_claim_links_id', table_name='witness_claim_links')
    op.drop_table('witness_claim_links')

    op.drop_index('ix_case_claims_matter_type_number', table_name='case_claims')
    op.drop_index('ix_case_claims_matter_id', table_name='case_claims')
    op.drop_index('ix_case_claims_id', table_name='case_claims')
    op.drop_table('case_claims')

    op.execute("DROP TYPE claimtype")
