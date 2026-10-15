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
    # --- CSAP table 2, items 1-10 ---
    # item 1 — total duration of speech (file minus recorder lead-in/lead-out).
    speech_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # item 2 — total duration of phonation: speech minus silent *and* filled
    # pauses. Filled-pause time can only be measured when the transcript carries
    # a word timeline, so this falls back to silent-only when it does not; the
    # effective coverage is recorded in `params["filled_pause_timed"]`.
    phonation_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # item 3 — total duration of silent pauses.
    silent_pause_total_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    silent_pause_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # items 4 and 5.
    silent_pause_mean_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    silent_pause_median_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Beyond table 2, but CSAP §2.3 names it explicitly as a computed variable.
    silent_pause_sd_ms: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # item 8 / 9 — syllables per minute over speech / phonation time.
    speech_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    articulation_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Word-based variants of the same two rates (not table 2; kept because the
    # paper notes syllables are the more representative unit, so both are useful
    # side by side when a reviewer asks).
    speech_rate_wpm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    articulation_rate_wpm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # item 10 — pause frequency, per 100 words.
    pause_rate_per_100_words: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # item 6 / 7.
    syllable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Filled pauses are annotated only to be removed (CSAP §2.3), but their
    # duration is what separates item 2 from item 3, so both the count and the
    # time are kept. NULL duration = no word timeline was available.
    filled_pause_count: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_pause_total_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # too_short | no_transcript | language_mismatch | NULL
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
