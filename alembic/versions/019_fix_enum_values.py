"""Fix enum values to ensure lowercase matches

Revision ID: 019
Revises: 018
Create Date: 2026-01-18
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Fix enum values by recreating them with correct lowercase values.
    PostgreSQL enums are case-sensitive, and we need lowercase values
    to match what SQLAlchemy is sending.
    """
    # Fix jobstatus enum
    op.execute("""
        -- Create new enum with lowercase values
        CREATE TYPE jobstatus_new AS ENUM ('pending', 'processing', 'completed', 'failed', 'cancelled');

        -- Update column to use new enum (cast handles value conversion)
        ALTER TABLE processing_jobs
        ALTER COLUMN status TYPE jobstatus_new
        USING (LOWER(status::text)::jobstatus_new);

        -- Drop old enum and rename new one
        DROP TYPE jobstatus;
        ALTER TYPE jobstatus_new RENAME TO jobstatus;
    """)

    # Fix syncstatus enum
    op.execute("""
        -- Create new enum with lowercase values
        CREATE TYPE syncstatus_new AS ENUM ('idle', 'syncing', 'failed');

        -- Update column to use new enum
        ALTER TABLE matters
        ALTER COLUMN sync_status TYPE syncstatus_new
        USING (LOWER(sync_status::text)::syncstatus_new);

        -- Drop old enum and rename new one
        DROP TYPE syncstatus;
        ALTER TYPE syncstatus_new RENAME TO syncstatus;
    """)

    # Fix witnessrole enum
    op.execute("""
        CREATE TYPE witnessrole_new AS ENUM (
            'plaintiff', 'defendant', 'eyewitness', 'expert', 'attorney',
            'physician', 'police_officer', 'family_member', 'colleague',
            'bystander', 'mentioned', 'other'
        );

        ALTER TABLE witnesses
        ALTER COLUMN role TYPE witnessrole_new
        USING (LOWER(role::text)::witnessrole_new);

        ALTER TABLE canonical_witnesses
        ALTER COLUMN role TYPE witnessrole_new
        USING (LOWER(role::text)::witnessrole_new);

        DROP TYPE witnessrole;
        ALTER TYPE witnessrole_new RENAME TO witnessrole;
    """)

    # Fix importancelevel enum
    op.execute("""
        CREATE TYPE importancelevel_new AS ENUM ('high', 'medium', 'low');

        ALTER TABLE witnesses
        ALTER COLUMN importance TYPE importancelevel_new
        USING (LOWER(importance::text)::importancelevel_new);

        DROP TYPE importancelevel;
        ALTER TYPE importancelevel_new RENAME TO importancelevel;
    """)

    # Fix relevancelevel enum
    op.execute("""
        CREATE TYPE relevancelevel_new AS ENUM ('highly_relevant', 'relevant', 'maybe_relevant', 'not_relevant');

        ALTER TABLE witnesses
        ALTER COLUMN relevance TYPE relevancelevel_new
        USING (LOWER(relevance::text)::relevancelevel_new);

        ALTER TABLE canonical_witnesses
        ALTER COLUMN relevance TYPE relevancelevel_new
        USING (LOWER(relevance::text)::relevancelevel_new);

        DROP TYPE relevancelevel;
        ALTER TYPE relevancelevel_new RENAME TO relevancelevel;
    """)

    # Fix claimtype enum
    op.execute("""
        CREATE TYPE claimtype_new AS ENUM ('allegation', 'defense');

        ALTER TABLE case_claims
        ALTER COLUMN claim_type TYPE claimtype_new
        USING (LOWER(claim_type::text)::claimtype_new);

        DROP TYPE claimtype;
        ALTER TYPE claimtype_new RENAME TO claimtype;
    """)


def downgrade() -> None:
    # No downgrade - this is a data fix
    pass
