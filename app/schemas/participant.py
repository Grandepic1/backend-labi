from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ParticipantCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    preferred_language: str = Field(default="id", max_length=10)


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    date_of_birth: date | None
    preferred_language: str
    created_at: datetime
    updated_at: datetime
