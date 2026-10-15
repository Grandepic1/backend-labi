from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class TrainingLogCreate(BaseModel):
    training_mode: str = Field(..., max_length=30, description="sfa | srt | cst")
    title: str = Field(..., max_length=150)
    status: str = Field(default="completed", max_length=20)
    duration_minutes: int | None = Field(default=None, ge=1, le=180)
    notes: str | None = Field(default=None, max_length=1000)


class TrainingLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    participant_id: int
    caregiver_id: int
    training_mode: str
    title: str
    status: str
    duration_minutes: int | None = None
    notes: str | None = None
    logged_at: datetime
    created_at: datetime


class HomeTrainingItem(BaseModel):
    training_mode: str  # "sfa" | "srt" | "cst"
    level: int          # 1 | 2 | 3
    level_title: str
    title: str
    target_area: str
    instructions: str
    frequency: str
    duration_minutes: int
    method_basis: str


class ActionableGuidanceRead(BaseModel):
    urgency_level: str  # "routine" | "needs_monitoring" | "medical_consultation_advised"
    medical_alert: str | None = None
    primary_mode: str
    secondary_mode: str | None = None
    target_goal: str
    overall_interpretation: str
    home_trainings: list[HomeTrainingItem] = []
    caregiver_daily_tips: list[str] = []


class SessionTrainingRecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    run_id: int
    participant_id: int
    urgency_level: str
    primary_mode: str
    secondary_mode: str | None = None
    target_goal: str
    overall_interpretation: str
    medical_alert: str | None = None
    home_trainings: list[HomeTrainingItem] = []
    created_at: datetime

