"""Add job recovery fields to processing_jobs

Adds last_activity_at and is_resumable columns to enable job recovery
after worker restarts.

Revision ID: 012
Revises: 011
Create Date: 2026-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '012'
down_revision = '011'
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


def upgrade() -> None:
    conn = op.get_bind()

    # Add last_activity_at column
    if not column_exists(conn, 'processing_jobs', 'last_activity_at'):
        op.add_column(
            'processing_jobs',
            sa.Column('last_activity_at', sa.DateTime(), nullable=True)
        )

    # Add is_resumable column
    if not column_exists(conn, 'processing_jobs', 'is_resumable'):
        op.add_column(
            'processing_jobs',
            sa.Column('is_resumable', sa.Boolean(), nullable=False, server_default='true')
        )


def downgrade() -> None:
    op.drop_column('processing_jobs', 'is_resumable')
    op.drop_column('processing_jobs', 'last_activity_at')
