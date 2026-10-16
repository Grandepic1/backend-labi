from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class SessionAnalysisRun(Base):
    __tablename__ = "session_analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_session_created", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    # running | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    asr_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # NOTE: no server_default — MySQL forbids defaults on JSON columns.
    requested_steps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionSpeechMetrics(Base):
    __tablename__ = "session_speech_metrics"
    __table_args__ = (
        Index("ix_speech_metrics_session_created", "session_id", "created_at"),
        Index("ix_speech_metrics_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("session_analysis_runs.id"), nullable=False)
    analysis_method: Mapped[str] = mapped_column(String(40), nullable=False)

    file_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lead_silence_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tail_silence_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    speech_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phonation_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    silent_pause_total_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    silent_pause_count: Mapped[int] = mapped_column(Integer, nullable=False)

    silent_pause_mean_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    silent_pause_median_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    silent_pause_sd_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # CSAP item 8 / 9: syllables per minute over speech / phonation time.
    speech_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    articulation_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Word-based variants of the same two rates.
    speech_rate_wpm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    articulation_rate_wpm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # CSAP item 10.
    pause_rate_per_100_words: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    syllable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_pause_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # too_short | no_transcript | NULL
    quality_flag: Mapped[str | None] = mapped_column(String(30), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionSilentPause(Base):
    __tablename__ = "session_silent_pauses"
    __table_args__ = (UniqueConstraint("run_id", "ordinal", name="uq_silent_pause_run_ordinal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("session_analysis_runs.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SessionIuSuggestion(Base):
    __tablename__ = "session_iu_suggestions"
    __table_args__ = (UniqueConstraint("run_id", "iu_id", name="uq_iu_suggestion_run_iu"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("session_analysis_runs.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    iu_id: Mapped[int] = mapped_column(Integer, ForeignKey("story_information_units.id"), nullable=False)
    # met | not_met | unclear
    suggested_status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
