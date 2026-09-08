"""fix is_gmail null handling

Revision ID: 72a603fe6339
Revises: 133789490c0b
Create Date: 2026-09-08 21:34:20.092259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72a603fe6339'
down_revision: Union[str, Sequence[str], None] = '133789490c0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Postgres doesn't support ALTER on a generated column's expression --
    it must be dropped and re-added. Fixes is_gmail producing NULL (and
    violating its own NOT NULL constraint) for contacts with no email,
    since `NULL LIKE '...'` evaluates to NULL, not false, in SQL.
    """
    op.drop_column('contacts', 'is_gmail')
    op.add_column(
        'contacts',
        sa.Column(
            'is_gmail',
            sa.Boolean(),
            sa.Computed("COALESCE(lower(email) LIKE '%@gmail.com', false)"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('contacts', 'is_gmail')
    op.add_column(
        'contacts',
        sa.Column(
            'is_gmail',
            sa.Boolean(),
            sa.Computed("lower(email) LIKE '%@gmail.com'"),
            nullable=False,
        ),
    )
