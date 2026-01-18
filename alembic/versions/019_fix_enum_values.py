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

    This migration handles partial runs by checking if types already exist.
    """

    # Fix jobstatus enum
    op.execute("""
        DO $$
        BEGIN
            -- Create new enum if it doesn't exist
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobstatus_new') THEN
                CREATE TYPE jobstatus_new AS ENUM ('pending', 'processing', 'completed', 'failed', 'cancelled');
            END IF;

            -- Drop default, alter type, restore default
            ALTER TABLE processing_jobs ALTER COLUMN status DROP DEFAULT;
            ALTER TABLE processing_jobs
                ALTER COLUMN status TYPE jobstatus_new
                USING (LOWER(status::text)::jobstatus_new);
            ALTER TABLE processing_jobs ALTER COLUMN status SET DEFAULT 'pending'::jobstatus_new;

            -- Drop old enum if it exists and rename new one
            DROP TYPE IF EXISTS jobstatus;
            ALTER TYPE jobstatus_new RENAME TO jobstatus;
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'jobstatus migration: %', SQLERRM;
        END $$;
    """)

    # Fix syncstatus enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'syncstatus_new') THEN
                CREATE TYPE syncstatus_new AS ENUM ('idle', 'syncing', 'failed');
            END IF;

            ALTER TABLE matters ALTER COLUMN sync_status DROP DEFAULT;
            ALTER TABLE matters
                ALTER COLUMN sync_status TYPE syncstatus_new
                USING (LOWER(sync_status::text)::syncstatus_new);
            ALTER TABLE matters ALTER COLUMN sync_status SET DEFAULT 'idle'::syncstatus_new;

            DROP TYPE IF EXISTS syncstatus;
            ALTER TYPE syncstatus_new RENAME TO syncstatus;
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'syncstatus migration: %', SQLERRM;
        END $$;
    """)

    # Fix witnessrole enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'witnessrole_new') THEN
                CREATE TYPE witnessrole_new AS ENUM (
                    'plaintiff', 'defendant', 'eyewitness', 'expert', 'attorney',
                    'physician', 'police_officer', 'family_member', 'colleague',
                    'bystander', 'mentioned', 'other'
                );
            END IF;

            ALTER TABLE witnesses
                ALTER COLUMN role TYPE witnessrole_new
                USING (LOWER(role::text)::witnessrole_new);

            ALTER TABLE canonical_witnesses
                ALTER COLUMN role TYPE witnessrole_new
                USING (LOWER(role::text)::witnessrole_new);

            DROP TYPE IF EXISTS witnessrole;
            ALTER TYPE witnessrole_new RENAME TO witnessrole;
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'witnessrole migration: %', SQLERRM;
        END $$;
    """)

    # Fix importancelevel enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'importancelevel_new') THEN
                CREATE TYPE importancelevel_new AS ENUM ('high', 'medium', 'low');
            END IF;

            ALTER TABLE witnesses
                ALTER COLUMN importance TYPE importancelevel_new
                USING (LOWER(importance::text)::importancelevel_new);

            DROP TYPE IF EXISTS importancelevel;
            ALTER TYPE importancelevel_new RENAME TO importancelevel;
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'importancelevel migration: %', SQLERRM;
        END $$;
    """)

    # Fix relevancelevel enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'relevancelevel_new') THEN
                CREATE TYPE relevancelevel_new AS ENUM ('highly_relevant', 'relevant', 'maybe_relevant', 'not_relevant');
            END IF;

            -- Drop defaults first
            ALTER TABLE witnesses ALTER COLUMN relevance DROP DEFAULT;
            ALTER TABLE canonical_witnesses ALTER COLUMN relevance DROP DEFAULT;

            ALTER TABLE witnesses
                ALTER COLUMN relevance TYPE relevancelevel_new
                USING (LOWER(relevance::text)::relevancelevel_new);

            ALTER TABLE canonical_witnesses
                ALTER COLUMN relevance TYPE relevancelevel_new
                USING (LOWER(relevance::text)::relevancelevel_new);

            -- Restore defaults
            ALTER TABLE witnesses ALTER COLUMN relevance SET DEFAULT 'relevant'::relevancelevel_new;
            ALTER TABLE canonical_witnesses ALTER COLUMN relevance SET DEFAULT 'relevant'::relevancelevel_new;

            DROP TYPE IF EXISTS relevancelevel;
            ALTER TYPE relevancelevel_new RENAME TO relevancelevel;
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'relevancelevel migration: %', SQLERRM;
        END $$;
    """)

    # Fix claimtype enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'claimtype_new') THEN
                CREATE TYPE claimtype_new AS ENUM ('allegation', 'defense');
            END IF;

            ALTER TABLE case_claims
                ALTER COLUMN claim_type TYPE claimtype_new
                USING (LOWER(claim_type::text)::claimtype_new);

            DROP TYPE IF EXISTS claimtype;
            ALTER TYPE claimtype_new RENAME TO claimtype;
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'claimtype migration: %', SQLERRM;
        END $$;
    """)


def downgrade() -> None:
    # No downgrade - this is a data fix
    pass
