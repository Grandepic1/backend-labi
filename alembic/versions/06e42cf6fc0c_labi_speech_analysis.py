from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "06e42cf6fc0c"
down_revision: str | None = "3f2a1b9c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_analysis_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("asr_model", sa.String(length=100), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("requested_steps", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_session_created", "session_analysis_runs", ["session_id", "created_at"])
    op.create_index("ix_session_analysis_runs_session_id", "session_analysis_runs", ["session_id"])

    op.create_table(
        "session_speech_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("analysis_method", sa.String(length=40), nullable=False),
        sa.Column("file_duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("lead_silence_ms", sa.BigInteger(), nullable=False),
        sa.Column("tail_silence_ms", sa.BigInteger(), nullable=False),
        sa.Column("speech_duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("phonation_ms", sa.BigInteger(), nullable=False),
        sa.Column("silent_pause_total_ms", sa.BigInteger(), nullable=False),
        sa.Column("silent_pause_count", sa.Integer(), nullable=False),
        sa.Column("silent_pause_mean_ms", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("silent_pause_median_ms", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("silent_pause_sd_ms", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("speech_rate", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("articulation_rate", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("speech_rate_wpm", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("articulation_rate_wpm", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("pause_rate_per_100_words", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("syllable_count", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("filled_pause_count", sa.Integer(), nullable=False),
        sa.Column("quality_flag", sa.String(length=30), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["session_analysis_runs.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_speech_metrics_session_id", "session_speech_metrics", ["session_id"])
    op.create_index("ix_speech_metrics_run_id", "session_speech_metrics", ["run_id"])
    op.create_index("ix_speech_metrics_session_created", "session_speech_metrics", ["session_id", "created_at"])

    op.create_table(
        "session_silent_pauses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["session_analysis_runs.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_silent_pause_run_ordinal"),
    )
    op.create_index("ix_session_silent_pauses_run_id", "session_silent_pauses", ["run_id"])

    op.create_table(
        "session_iu_suggestions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("iu_id", sa.Integer(), nullable=False),
        sa.Column("suggested_status", sa.String(length=20), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["iu_id"], ["story_information_units.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["session_analysis_runs.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "iu_id", name="uq_iu_suggestion_run_iu"),
    )
    op.create_index("ix_session_iu_suggestions_run_id", "session_iu_suggestions", ["run_id"])
    op.create_index("ix_session_iu_suggestions_session_id", "session_iu_suggestions", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_session_iu_suggestions_session_id", table_name="session_iu_suggestions")
    op.drop_index("ix_session_iu_suggestions_run_id", table_name="session_iu_suggestions")
    op.drop_table("session_iu_suggestions")

    op.drop_index("ix_session_silent_pauses_run_id", table_name="session_silent_pauses")
    op.drop_table("session_silent_pauses")

    op.drop_index("ix_speech_metrics_session_created", table_name="session_speech_metrics")
    op.drop_index("ix_speech_metrics_run_id", table_name="session_speech_metrics")
    op.drop_index("ix_session_speech_metrics_session_id", table_name="session_speech_metrics")
    op.drop_table("session_speech_metrics")

    op.drop_index("ix_session_analysis_runs_session_id", table_name="session_analysis_runs")
    op.drop_index("ix_analysis_runs_session_created", table_name="session_analysis_runs")
    op.drop_table("session_analysis_runs")
