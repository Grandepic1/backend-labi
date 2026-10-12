"""Schemas for the survivor personalization / onboarding profile.

The allowed values mirror the options the app offers during personalization
(``lib/survivorOptions.ts``) so the API rejects anything the UI cannot produce.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Nama panggilan penyintas — matches the varchar(50) column.
MAX_NAME_LENGTH = 50


class AgeRange(str, Enum):
    AGE_60_69 = "60-69"
    AGE_70_79 = "70-79"
    AGE_80_PLUS = "80+"


class PrimaryLanguage(str, Enum):
    INDONESIAN = "id"
    JAVANESE = "jv"
    SUNDANESE = "su"
    MADURESE = "md"
    BUGINESE = "bug"
    OTHER = "other"


class CommunicationGoal(str, Enum):
    EVERYDAY_STORYTELLING = "everyday_storytelling"
    ANSWERING_QUESTIONS = "answering_questions"
    RETELLING_STORY = "retelling_story"
    EXPRESSING_NEEDS = "expressing_needs"
    EXPLORE_FIRST = "explore_first"


class InstructionPreference(str, Enum):
    INDEPENDENT = "independent"
    SHORT_SIMPLE = "short_simple"
    COMPANION_ASSISTANCE = "companion_assistance"
    UNKNOWN = "unknown"


class PreferredSessionDuration(str, Enum):
    THREE_MINUTES = "3"
    FIVE_MINUTES = "5"
    TEN_MINUTES = "10"
    UNKNOWN = "unknown"


class ConversationTopic(str, Enum):
    FAMILY = "family"
    HOBBIES = "hobbies"
    FOOD = "food"
    DAILY_ACTIVITIES = "daily_activities"
    MEMORIES = "memories"
    OTHER = "other"


class PracticeMode(str, Enum):
    INDEPENDENT = "independent"
    COMPANION = "companion"
    BOTH = "both"


class SurvivorProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    age_range: AgeRange | None = None
    primary_language: PrimaryLanguage | None = None
    communication_goals: list[CommunicationGoal] = Field(default_factory=list)
    instruction_preference: InstructionPreference | None = None
    preferred_session_duration: PreferredSessionDuration | None = None
    preferred_topics: list[ConversationTopic] = Field(default_factory=list)
    practice_mode: PracticeMode | None = None
    personalization_confirmed: bool = False

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("communication_goals", "preferred_topics")
    @classmethod
    def _dedupe_preserving_order(cls, value: list[Enum]) -> list[Enum]:
        seen: set[Enum] = set()
        unique: list[Enum] = []
        for item in value:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique


class SurvivorProfileUpsert(SurvivorProfileBase):
    """Body for creating or updating the companion's survivor profile."""


class SurvivorProfileRead(SurvivorProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
