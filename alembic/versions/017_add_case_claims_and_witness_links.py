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
    # Create claim_type enum if it doesn't exist
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE claimtype AS ENUM ('allegation', 'defense');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create case_claims table
    op.execute("""
        CREATE TABLE case_claims (
            id SERIAL PRIMARY KEY,
            matter_id INTEGER NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
            claim_type claimtype NOT NULL,
            claim_number INTEGER NOT NULL,
            claim_text TEXT NOT NULL,
            source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            source_page INTEGER,
            extraction_method VARCHAR(20) NOT NULL DEFAULT 'discovery',
            confidence_score FLOAT,
            is_verified BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW() NOT NULL
        )
    """)

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
    op.execute("""
        CREATE TABLE witness_claim_links (
            id SERIAL PRIMARY KEY,
            witness_id INTEGER NOT NULL REFERENCES witnesses(id) ON DELETE CASCADE,
            case_claim_id INTEGER NOT NULL REFERENCES case_claims(id) ON DELETE CASCADE,
            relevance_explanation TEXT,
            supports_or_undermines VARCHAR(20) NOT NULL DEFAULT 'neutral',
            created_at TIMESTAMP DEFAULT NOW() NOT NULL
        )
    """)

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

    op.execute("DROP TYPE IF EXISTS claimtype")
