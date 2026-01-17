"""Add canonical witnesses for deduplication

Revision ID: 016
Revises: 015
Create Date: 2026-01-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create canonical_witnesses table
    op.create_table(
        'canonical_witnesses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('matter_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('plaintiff', 'defendant', 'eyewitness', 'expert', 'attorney',
                                   'physician', 'police_officer', 'family_member', 'colleague',
                                   'bystander', 'mentioned', 'other', name='witnessrole'), nullable=False),
        sa.Column('relevance', sa.Enum('highly_relevant', 'relevant', 'somewhat_relevant', 'not_relevant',
                                        name='relevancelevel'), nullable=True),
        sa.Column('relevance_reason', sa.Text(), nullable=True),
        sa.Column('merged_observations', sa.JSON(), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(100), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('source_document_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('max_confidence_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
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
