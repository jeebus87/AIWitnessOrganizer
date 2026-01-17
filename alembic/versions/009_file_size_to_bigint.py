"""Change file_size from INTEGER to BIGINT for files >2GB

Revision ID: 009
Revises: 008
Create Date: 2025-01-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Change file_size from INTEGER to BIGINT to support files >2GB
    op.alter_column(
        'documents',
        'file_size',
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        'documents',
        'file_size',
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=True
    )
