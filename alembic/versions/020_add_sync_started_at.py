"""Add sync_started_at column to matters table

Revision ID: 020
Revises: 019
Create Date: 2026-01-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '020'
down_revision: Union[str, None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add sync_started_at column to track when sync began (for stale detection)
    op.add_column('matters', sa.Column('sync_started_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('matters', 'sync_started_at')
