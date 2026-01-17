"""Add job_id column to witnesses table

This allows tracking which job created each witness, enabling job-specific exports
instead of exporting all witnesses for a matter.

Revision ID: 011
Revises: 010
Create Date: 2026-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '011'
down_revision = '010'
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


def constraint_exists(conn, constraint_name):
    """Check if a foreign key constraint exists."""
    result = conn.execute(text(f"""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = '{constraint_name}'
        )
    """))
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # Add job_id column to witnesses if it doesn't exist
    if not column_exists(conn, 'witnesses', 'job_id'):
        op.add_column(
            'witnesses',
            sa.Column('job_id', sa.Integer(), nullable=True)
        )

    # Add index on job_id for faster queries if it doesn't exist
    if not index_exists(conn, 'ix_witnesses_job_id'):
        op.create_index('ix_witnesses_job_id', 'witnesses', ['job_id'])

    # Add foreign key constraint if it doesn't exist
    if not constraint_exists(conn, 'fk_witnesses_job_id'):
        op.create_foreign_key(
            'fk_witnesses_job_id',
            'witnesses',
            'processing_jobs',
            ['job_id'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade() -> None:
    op.drop_constraint('fk_witnesses_job_id', 'witnesses', type_='foreignkey')
    op.drop_index('ix_witnesses_job_id', table_name='witnesses')
    op.drop_column('witnesses', 'job_id')
