"""Increase file_type column length from 50 to 128

Revision ID: 008
Revises: 007
Create Date: 2025-01-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Increase file_type column length to accommodate long MIME types
    # like "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    op.alter_column(
        'documents',
        'file_type',
        type_=sa.String(128),
        existing_type=sa.String(50),
        existing_nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        'documents',
        'file_type',
        type_=sa.String(50),
        existing_type=sa.String(128),
        existing_nullable=True
    )
