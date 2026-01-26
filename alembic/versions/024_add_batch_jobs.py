"""Add batch_jobs table for AWS Bedrock batch inference tracking

Revision ID: 024
Revises: 023
Create Date: 2026-01-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Create batchjobtype enum if it doesn't exist
    result = bind.execute(sa.text(
        "SELECT 1 FROM pg_type WHERE typname = 'batchjobtype'"
    ))
    if not result.fetchone():
        op.execute("CREATE TYPE batchjobtype AS ENUM ('witness_extraction', 'legal_research')")

    # Create batch_jobs table if it doesn't exist
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'batch_jobs'"
    ))
    if not result.fetchone():
        op.create_table(
            'batch_jobs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('processing_job_id', sa.Integer(), nullable=True),
            sa.Column('aws_job_arn', sa.String(500), nullable=False),
            sa.Column('job_type', postgresql.ENUM('witness_extraction', 'legal_research', name='batchjobtype', create_type=False), nullable=False),
            sa.Column('status', sa.String(50), nullable=False, server_default='Submitted'),
            sa.Column('input_s3_uri', sa.String(500), nullable=False),
            sa.Column('output_s3_uri', sa.String(500), nullable=True),
            sa.Column('total_records', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('processed_records', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('submitted_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('results_json', postgresql.JSON(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('user_notified', sa.Boolean(), nullable=False, server_default='false'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['processing_job_id'], ['processing_jobs.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_batch_jobs_id', 'batch_jobs', ['id'])
        op.create_index('ix_batch_jobs_user_id', 'batch_jobs', ['user_id'])
        op.create_index('ix_batch_jobs_status', 'batch_jobs', ['status'])
        op.create_unique_constraint('uq_batch_jobs_aws_job_arn', 'batch_jobs', ['aws_job_arn'])


def downgrade():
    op.drop_table('batch_jobs')
    op.execute("DROP TYPE IF EXISTS batchjobtype")
