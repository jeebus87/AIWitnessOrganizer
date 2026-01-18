"""Add canonical witnesses for deduplication

Revision ID: 016
Revises: 015
Create Date: 2026-01-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create canonical_witnesses table using existing enum types
    # witnessrole and relevancelevel already exist from initial schema
    op.execute("""
        CREATE TABLE canonical_witnesses (
            id SERIAL PRIMARY KEY,
            matter_id INTEGER NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
            full_name VARCHAR(255) NOT NULL,
            role witnessrole NOT NULL,
            relevance relevancelevel,
            relevance_reason TEXT,
            merged_observations JSONB,
            email VARCHAR(255),
            phone VARCHAR(100),
            address TEXT,
            source_document_count INTEGER NOT NULL DEFAULT 1,
            max_confidence_score FLOAT,
            created_at TIMESTAMP DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW() NOT NULL
        )
    """)

    op.create_index('ix_canonical_witnesses_id', 'canonical_witnesses', ['id'])
    op.create_index('ix_canonical_witnesses_matter_id', 'canonical_witnesses', ['matter_id'])
    op.create_index('ix_canonical_witnesses_full_name', 'canonical_witnesses', ['full_name'])

    # Add canonical_witness_id to witnesses table
    op.add_column('witnesses', sa.Column('canonical_witness_id', sa.Integer(), nullable=True))
    op.create_index('ix_witnesses_canonical_witness_id', 'witnesses', ['canonical_witness_id'])
    op.create_foreign_key(
        'fk_witnesses_canonical_witness_id',
        'witnesses', 'canonical_witnesses',
        ['canonical_witness_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_witnesses_canonical_witness_id', 'witnesses', type_='foreignkey')
    op.drop_index('ix_witnesses_canonical_witness_id', table_name='witnesses')
    op.drop_column('witnesses', 'canonical_witness_id')
    op.drop_index('ix_canonical_witnesses_full_name', table_name='canonical_witnesses')
    op.drop_index('ix_canonical_witnesses_matter_id', table_name='canonical_witnesses')
    op.drop_index('ix_canonical_witnesses_id', table_name='canonical_witnesses')
    op.drop_table('canonical_witnesses')
