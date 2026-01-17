"""Add is_archived and archived_at columns to processing_jobs

Revision ID: 010
Revises: 009
Create Date: 2026-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '010'
down_revision = '009'
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

    # Add is_archived column with default False if it doesn't exist
    if not column_exists(conn, 'processing_jobs', 'is_archived'):
        op.add_column(
            'processing_jobs',
            sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false')
        )

    # Add archived_at timestamp column if it doesn't exist
    if not column_exists(conn, 'processing_jobs', 'archived_at'):
        op.add_column(
            'processing_jobs',
            sa.Column('archived_at', sa.DateTime(), nullable=True)
        )

    # Add index for faster queries on archived status if it doesn't exist
    if not index_exists(conn, 'ix_processing_jobs_is_archived'):
        op.create_index('ix_processing_jobs_is_archived', 'processing_jobs', ['is_archived'])


def downgrade() -> None:
    op.drop_index('ix_processing_jobs_is_archived', table_name='processing_jobs')
    op.drop_column('processing_jobs', 'archived_at')
    op.drop_column('processing_jobs', 'is_archived')
