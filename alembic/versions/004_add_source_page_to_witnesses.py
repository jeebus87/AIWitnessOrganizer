"""Add source_page column to witnesses table

Revision ID: 004
Revises: 003_increase_phone_column
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_source_page'
down_revision: Union[str, None] = '003_increase_phone_column'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add source_page column to witnesses table
    op.add_column(
        'witnesses',
        sa.Column('source_page', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    # Remove source_page column
    op.drop_column('witnesses', 'source_page')
