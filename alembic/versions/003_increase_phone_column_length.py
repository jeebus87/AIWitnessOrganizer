"""Increase phone column length in witnesses table

Revision ID: 003
Revises: 002_rename_firebase_uid
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_increase_phone_column'
down_revision: Union[str, None] = '002_rename_firebase_uid'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Increase phone column length from VARCHAR(50) to VARCHAR(100)
    # to accommodate phone numbers with extensions
    op.alter_column(
        'witnesses',
        'phone',
        type_=sa.String(100),
        existing_type=sa.String(50),
        existing_nullable=True
    )


def downgrade() -> None:
    # Revert to VARCHAR(50)
    op.alter_column(
        'witnesses',
        'phone',
        type_=sa.String(50),
        existing_type=sa.String(100),
        existing_nullable=True
    )
