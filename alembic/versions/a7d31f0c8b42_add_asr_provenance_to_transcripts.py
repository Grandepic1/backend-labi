"""add asr provenance columns to transcripts

Adds the language identified in the audio (not the forced transcription
language), its confidence, and the word-level timeline. Together these make a
language mismatch visible instead of silent, and give the pause timeline
something to align against (CSAP items 11-18).

Revision ID: a7d31f0c8b42
Revises: f33631210fa9
Create Date: 2026-10-15 06:30:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d31f0c8b42'
down_revision: str | None = 'f33631210fa9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('transcripts', sa.Column('language', sa.String(length=10), nullable=True))
    op.add_column('transcripts', sa.Column('language_probability', sa.Float(), nullable=True))
    op.add_column('transcripts', sa.Column('segments', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('transcripts', 'segments')
    op.drop_column('transcripts', 'language_probability')
    op.drop_column('transcripts', 'language')
