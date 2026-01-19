"""Add legal research results table

Revision ID: 022
Revises: 021
Create Date: 2025-01-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade():
    # Create the legal_research_status enum type if it doesn't exist
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT 1 FROM pg_type WHERE typname = 'legalresearchstatus'"
    ))
    if not result.fetchone():
        op.execute("CREATE TYPE legalresearchstatus AS ENUM ('pending', 'ready', 'approved', 'completed', 'dismissed')")

    # Check if table already exists
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'legal_research_results'"
    ))
    if result.fetchone():
        # Table already exists, skip creation
        return

    # Create legal_research_results table using the existing enum type
    op.create_table(
        'legal_research_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('matter_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'ready', 'approved', 'completed', 'dismissed',
                                             name='legalresearchstatus', create_type=False),
                  nullable=False, server_default='pending'),
        sa.Column('results', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('selected_ids', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('clio_folder_id', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['processing_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes (only if table was just created)
    op.create_index('ix_legal_research_results_job_id', 'legal_research_results', ['job_id'], if_not_exists=True)
    op.create_index('ix_legal_research_results_matter_id', 'legal_research_results', ['matter_id'], if_not_exists=True)
    op.create_index('ix_legal_research_results_user_id', 'legal_research_results', ['user_id'], if_not_exists=True)


def downgrade():
    # Drop table and indexes
    op.drop_index('ix_legal_research_results_user_id', table_name='legal_research_results')
    op.drop_index('ix_legal_research_results_matter_id', table_name='legal_research_results')
    op.drop_index('ix_legal_research_results_job_id', table_name='legal_research_results')
    op.drop_table('legal_research_results')

    # Drop the enum type
    op.execute('DROP TYPE IF EXISTS legalresearchstatus')
