from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IURead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    description: str
    accepted_variants: list[str] = []
    scoring_rule: str
    display_order: int


class StoryListItem(BaseModel):
    id: int
    title: str
    version: int
    estimated_duration_seconds: int | None = None
    iu_count: int


class StoryDetail(BaseModel):
    id: int
    title: str
    version: int
    story_text: str
    instructions: str
    ius: list[IURead]


# --- Admin (story/IU management) ---


class StoryCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    story_text: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    language: str = Field(default="id", max_length=10)
    estimated_duration_seconds: int | None = Field(default=None, ge=0)


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    story_text: str | None = None
    instructions: str | None = None
    language: str | None = Field(default=None, max_length=10)
    estimated_duration_seconds: int | None = Field(default=None, ge=0)


class IUCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1)
    scoring_rule: str = Field(min_length=1)
    accepted_variants: list[str] = []
    display_order: int = Field(ge=0)


class IUUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=20)
    description: str | None = None
    scoring_rule: str | None = None
    accepted_variants: list[str] | None = None
    display_order: int | None = Field(default=None, ge=0)


class StoryVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    story_id: int
    version_number: int
    title: str
    status: str
    published_at: datetime | None
    created_at: datetime
