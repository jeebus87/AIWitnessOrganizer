"""Add job_number column and organization_job_counters table

Revision ID: 007
Revises: 006
Create Date: 2025-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def column_exists(conn, table_name, column_name):
    """Check if a column exists in a table."""
    result = conn.execute(text(f"""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.columns
            WHERE table_name = '{table_name}' AND column_name = '{column_name}'
        )
    """))
    return result.scalar()


def table_exists(conn, table_name):
    """Check if a table exists in the database."""
    result = conn.execute(text(f"""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables WHERE table_name = '{table_name}'
        )
    """))
    return result.scalar()


def index_exists(conn, index_name):
    """Check if an index exists in the database."""
    result = conn.execute(text(f"""
        SELECT EXISTS(
            SELECT 1 FROM pg_indexes WHERE indexname = '{index_name}'
        )
    """))
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # Add job_number column to processing_jobs if it doesn't exist
    if not column_exists(conn, 'processing_jobs', 'job_number'):
        op.add_column('processing_jobs', sa.Column('job_number', sa.Integer(), nullable=True))

    # Create index if it doesn't exist
    if not index_exists(conn, 'ix_processing_jobs_job_number'):
        op.create_index('ix_processing_jobs_job_number', 'processing_jobs', ['job_number'])

    # Create organization_job_counters table if it doesn't exist
    # (It may have been created in migration 005)
    if not table_exists(conn, 'organization_job_counters'):
        op.create_table(
            'organization_job_counters',
            sa.Column('organization_id', sa.Integer(), nullable=False),
            sa.Column('job_counter', sa.Integer(), nullable=False, server_default='0'),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('organization_id')
        )


def downgrade() -> None:
    # Note: We don't drop organization_job_counters here since it might have been
    # created in migration 005
    op.drop_index('ix_processing_jobs_job_number', table_name='processing_jobs')
    op.drop_column('processing_jobs', 'job_number')
