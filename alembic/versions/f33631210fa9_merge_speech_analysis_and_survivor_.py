"""merge speech analysis and survivor profile heads

Revision ID: f33631210fa9
Revises: 06e42cf6fc0c, 3c4e40c44fc5
Create Date: 2026-10-14 00:16:57.327265

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f33631210fa9'
down_revision: str | None = ('06e42cf6fc0c', '3c4e40c44fc5')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
