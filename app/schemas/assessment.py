from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IUStatus = Literal["met", "not_met", "unclear"]


class AssessmentItemIn(BaseModel):
    iu_id: int
    status: IUStatus
    evidence_note: str | None = Field(default=None, max_length=2000)


class AssessmentUpsert(BaseModel):
    items: list[AssessmentItemIn] = Field(min_length=1)


class AssessmentRead(BaseModel):
    session_id: int
    assessment_status: str  # in_progress
    met_count: int
    not_met_count: int
    unclear_count: int
    total_iu: int
    provisional_recall_percent: float | None
    is_final: bool = False
    updated_at: datetime


class CompleteIn(BaseModel):
    confirm: bool = True


class CompleteResult(BaseModel):
    met_count: int
    not_met_count: int
    total_iu: int
    iu_recall_percent: float


class CompleteOut(BaseModel):
    session_id: int
    status: str
    result: CompleteResult
    completed_at: datetime


class ResultItemRead(BaseModel):
    iu_id: int
    code: str
    description: str
    status: str
    evidence_note: str | None = None


class ResultRead(BaseModel):
    session_id: int
    status: str
    met_count: int
    not_met_count: int
    unclear_count: int
    total_iu: int
    iu_recall_percent: float | None
    story_id: int
    story_version_id: int
    story_title: str
    assessor_id: int | None = None
    completed_at: datetime | None = None
    has_recording: bool = False
    items: list[ResultItemRead] = []
