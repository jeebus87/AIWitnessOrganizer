"""Rename firebase_uid to clio_user_id in users table

Revision ID: 002
Revises: 001
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_rename_firebase_uid'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename the column
    op.alter_column('users', 'firebase_uid', new_column_name='clio_user_id')

    # Rename the index (drop old, create new)
    op.drop_index('ix_users_firebase_uid', table_name='users')
    op.create_index('ix_users_clio_user_id', 'users', ['clio_user_id'], unique=True)


def downgrade() -> None:
    # Rename back
    op.alter_column('users', 'clio_user_id', new_column_name='firebase_uid')

    # Rename the index back
    op.drop_index('ix_users_clio_user_id', table_name='users')
    op.create_index('ix_users_firebase_uid', 'users', ['firebase_uid'], unique=True)
