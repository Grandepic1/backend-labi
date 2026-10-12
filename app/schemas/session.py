from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    participant_id: int
    story_id: int
    task_type: str = Field(default="immediate_recall", max_length=30)
    session_note: str | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    participant_id: int
    story_id: int
    story_version_id: int
    task_type: str
    status: str
    created_at: datetime


class RecordingRead(BaseModel):
    id: int
    session_id: int
    storage_status: str = "stored"
    duration_ms: int | None = None
    mime_type: str
    file_size_bytes: int
    created_at: datetime
    playback_url: str


class TranscriptUpsert(BaseModel):
    text: str = Field(min_length=1)
    source: str = Field(default="manual", max_length=20)
    review_status: str = Field(default="draft", max_length=20)


class TranscriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    recording_id: int
    text: str
    source: str
    review_status: str
    created_at: datetime
    updated_at: datetime


class SessionHistoryItem(BaseModel):
    id: int
    participant_id: int
    story_title: str | None = None
    story_version: int | None = None
    status: str
    iu_recall_percent: float | None = None
    completed_at: datetime | None = None
    has_recording: bool = False


class PaginatedSessions(BaseModel):
    data: list[SessionHistoryItem]
    pagination: dict
