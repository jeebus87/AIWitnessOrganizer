"""Add somewhat_relevant to relevancelevel enum

Revision ID: 020
Revises: 019
Create Date: 2026-01-18
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'somewhat_relevant' to relevancelevel enum if not exists
    op.execute("""
        DO $$
        BEGIN
            -- Check if somewhat_relevant already exists in the enum
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'somewhat_relevant'
                AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'relevancelevel')
            ) THEN
                ALTER TYPE relevancelevel ADD VALUE IF NOT EXISTS 'somewhat_relevant' AFTER 'relevant';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Cannot remove enum values in PostgreSQL easily, so just leave it
    pass
