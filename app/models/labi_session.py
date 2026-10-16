from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_participant_created", "participant_id", "created_at"),
        Index("ix_sessions_caregiver_created", "caregiver_id", "created_at"),
        Index("ix_sessions_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[int] = mapped_column(Integer, ForeignKey("participants.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False)
    story_version_id: Mapped[int] = mapped_column(Integer, ForeignKey("story_versions.id"), nullable=False)
    caregiver_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # MVP: immediate_recall. Delayed recall later needs explicit type+interval.
    task_type: Mapped[str] = mapped_column(String(30), nullable=False, default="immediate_recall", server_default="immediate_recall")
    # created | recording_uploaded | assessment_in_progress | completed | cancelled
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created", server_default="created")
    session_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("session_id", name="uq_recordings_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="local_private", server_default="local_private")
    # Relative object key under STORAGE_DIR, never a public URL.
    # String(512) + UNIQUE: MySQL cannot build a UNIQUE index on TEXT.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    recording_id: Mapped[int] = mapped_column(Integer, ForeignKey("recordings.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # manual | asr
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    # draft | reviewed
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SessionAssessment(Base):
    __tablename__ = "session_assessments"
    __table_args__ = (UniqueConstraint("session_id", name="uq_assessments_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False)
    assessor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # draft | final
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    total_iu: Mapped[int] = mapped_column(Integer, nullable=False)
    met_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    not_met_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unclear_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    iu_recall_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    finalized_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SessionAssessmentItem(Base):
    __tablename__ = "session_assessment_items"
    __table_args__ = (
        UniqueConstraint("assessment_id", "iu_id", name="uq_assessment_iu"),
        Index("ix_assessment_items_assessment", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("session_assessments.id"), nullable=False)
    iu_id: Mapped[int] = mapped_column(Integer, ForeignKey("story_information_units.id"), nullable=False)
    # met | not_met | unclear
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_actor", "actor_user_id"),
        Index("ix_audit_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionTrainingLog(Base):
    __tablename__ = "session_training_logs"
    __table_args__ = (
        Index("ix_training_logs_session", "session_id"),
        Index("ix_training_logs_participant", "participant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    participant_id: Mapped[int] = mapped_column(Integer, ForeignKey("participants.id"), nullable=False, index=True)
    caregiver_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    training_mode: Mapped[str] = mapped_column(String(30), nullable=False)  # sfa | srt | cst
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed", server_default="completed")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionTrainingRecommendation(Base):
    __tablename__ = "session_training_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("session_analysis_runs.id"), nullable=False, index=True)
    participant_id: Mapped[int] = mapped_column(Integer, ForeignKey("participants.id"), nullable=False, index=True)
    urgency_level: Mapped[str] = mapped_column(String(50), nullable=False)  # routine | moderate | high | medical_consultation_advised
    primary_mode: Mapped[str] = mapped_column(String(30), nullable=False)  # sfa | srt | cst
    secondary_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_goal: Mapped[str] = mapped_column(Text, nullable=False)
    overall_interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    medical_alert: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_trainings: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

