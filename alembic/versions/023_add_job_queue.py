"""Add job queue support - QUEUED status and queued_at column

Revision ID: 023
Revises: 022
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Add 'queued' value to jobstatus enum if it doesn't exist
    # PostgreSQL requires ALTER TYPE to add enum values
    result = bind.execute(sa.text(
        "SELECT 1 FROM pg_enum WHERE enumlabel = 'queued' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'jobstatus')"
    ))
    if not result.fetchone():
        # Add 'queued' before 'pending' in the enum
        op.execute("ALTER TYPE jobstatus ADD VALUE 'queued' BEFORE 'pending'")

    # Add queued_at column if it doesn't exist
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'processing_jobs' AND column_name = 'queued_at'"
    ))
    if not result.fetchone():
        op.add_column('processing_jobs', sa.Column('queued_at', sa.DateTime(), nullable=True))

    # Add retry_count column to documents if it doesn't exist (from no-failure policy)
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'documents' AND column_name = 'retry_count'"
    ))
    if not result.fetchone():
        op.add_column('documents', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    # Note: PostgreSQL doesn't support removing enum values
    # We can only drop the column
    op.drop_column('processing_jobs', 'queued_at')
    op.drop_column('documents', 'retry_count')
