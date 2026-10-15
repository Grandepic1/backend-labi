"""asr model provenance on transcripts, filled-pause duration on metrics

Two additions that have to land before any dataset rebuild:

1. `transcripts` gains the model that produced the text. Rebuilding on a
   heavier ASR model changes the transcript text itself (word_timestamps alone
   already altered session 26 deterministically), which moves every syllable
   and word count derived from it. Without a stored model name the old and new
   transcripts are indistinguishable, and a dataset that silently mixes them
   cannot be defended.

2. `session_speech_metrics` gains the measured filled-pause duration. CSAP
   table 2 item 2 defines phonation as speech minus silent *and* filled pauses;
   without the filled-pause term, phonation was overstated and articulation
   rate (item 9) understated. NULL means the transcript carried no word
   timeline, so the term could not be measured.

Revision ID: b8e42a1d9c53
Revises: a7d31f0c8b42
Create Date: 2026-10-15 07:45:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e42a1d9c53'
down_revision: str | None = 'a7d31f0c8b42'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('transcripts', sa.Column('asr_model', sa.String(length=100), nullable=True))
    op.add_column('transcripts', sa.Column('asr_compute_type', sa.String(length=20), nullable=True))
    op.add_column('transcripts', sa.Column('asr_device', sa.String(length=20), nullable=True))
    op.add_column('session_speech_metrics', sa.Column('filled_pause_total_ms', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('session_speech_metrics', 'filled_pause_total_ms')
    op.drop_column('transcripts', 'asr_device')
    op.drop_column('transcripts', 'asr_compute_type')
    op.drop_column('transcripts', 'asr_model')
