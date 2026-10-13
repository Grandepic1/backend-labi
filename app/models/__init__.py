"""Register models here so Alembic autogenerate can see them."""

from app.core.database import Base
from app.models.labi_analysis import (
    SessionAnalysisRun,
    SessionIuSuggestion,
    SessionSilentPause,
    SessionSpeechMetrics,
)
from app.models.labi_session import (
    AuditLog,
    Recording,
    Session,
    SessionAssessment,
    SessionAssessmentItem,
    Transcript,
)
from app.models.participant import Participant
from app.models.story import Story, StoryInformationUnit, StoryVersion
from app.models.Users import Users

__all__ = [
    "AuditLog",
    "Base",
    "Participant",
    "Recording",
    "Session",
    "SessionAnalysisRun",
    "SessionAssessment",
    "SessionAssessmentItem",
    "SessionIuSuggestion",
    "SessionSilentPause",
    "SessionSpeechMetrics",
    "Story",
    "StoryInformationUnit",
    "StoryVersion",
    "Transcript",
    "Users",
]
