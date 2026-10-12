from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f2a1b9c4d5e"
down_revision: str | None = "96eb3bcc1c7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Users: Labi roles
    op.add_column("users", sa.Column("role", sa.String(length=20), server_default="caregiver", nullable=False))
    op.add_column("users", sa.Column("status", sa.String(length=20), server_default="active", nullable=False))

    op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("preferred_language", sa.String(length=10), server_default="id", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_participants_created_by", "participants", ["created_by"])

    op.create_table(
        "stories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_stories_status", "stories", ["status"])

    op.create_table(
        "story_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("story_text", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), server_default="id", nullable=False),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "version_number", name="uq_story_version_number"),
    )
    op.create_index("ix_story_versions_story_id", "story_versions", ["story_id"])
    op.create_index("ix_story_versions_status", "story_versions", ["status"])

    op.create_table(
        "story_information_units",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_version_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scoring_rule", sa.Text(), nullable=False),
        sa.Column("accepted_variants", sa.JSON(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["story_version_id"], ["story_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_version_id", "code", name="uq_version_iu_code"),
    )
    op.create_index("ix_iu_version_id", "story_information_units", ["story_version_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("story_version_id", sa.Integer(), nullable=False),
        sa.Column("caregiver_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=30), server_default="immediate_recall", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="created", nullable=False),
        sa.Column("session_note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["caregiver_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.ForeignKeyConstraint(["story_version_id"], ["story_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_participant_id", "sessions", ["participant_id"])
    op.create_index("ix_sessions_caregiver_id", "sessions", ["caregiver_id"])
    op.create_index("ix_sessions_participant_created", "sessions", ["participant_id", "created_at"])
    op.create_index("ix_sessions_caregiver_created", "sessions", ["caregiver_id", "created_at"])
    op.create_index("ix_sessions_status", "sessions", ["status"])

    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("storage_provider", sa.String(length=30), server_default="local_private", nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_recordings_session"),
        sa.UniqueConstraint("storage_key"),
    )

    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("review_status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcripts_session_id", "transcripts", ["session_id"])

    op.create_table(
        "session_assessments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("assessor_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("total_iu", sa.Integer(), nullable=False),
        sa.Column("met_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("not_met_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unclear_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("iu_recall_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assessor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_assessments_session"),
    )

    op.create_table(
        "session_assessment_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("iu_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["session_assessments.id"]),
        sa.ForeignKeyConstraint(["iu_id"], ["story_information_units.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "iu_id", name="uq_assessment_iu"),
    )
    op.create_index("ix_assessment_items_assessment", "session_assessment_items", ["assessment_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_actor", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_action", table_name="audit_logs")
    op.drop_index("ix_audit_actor", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_assessment_items_assessment", table_name="session_assessment_items")
    op.drop_table("session_assessment_items")
    op.drop_table("session_assessments")
    op.drop_index("ix_transcripts_session_id", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_table("recordings")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_index("ix_sessions_caregiver_created", table_name="sessions")
    op.drop_index("ix_sessions_participant_created", table_name="sessions")
    op.drop_index("ix_sessions_caregiver_id", table_name="sessions")
    op.drop_index("ix_sessions_participant_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_iu_version_id", table_name="story_information_units")
    op.drop_table("story_information_units")
    op.drop_index("ix_story_versions_status", table_name="story_versions")
    op.drop_index("ix_story_versions_story_id", table_name="story_versions")
    op.drop_table("story_versions")
    op.drop_index("ix_stories_status", table_name="stories")
    op.drop_table("stories")
    op.drop_index("ix_participants_created_by", table_name="participants")
    op.drop_table("participants")
    op.drop_column("users", "status")
    op.drop_column("users", "role")
