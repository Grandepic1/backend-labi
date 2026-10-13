from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.sql import func

from app.core.database import Base


class SurvivorProfiles(Base):
    """Personalization (onboarding) profile a companion fills in for the
    survivor (penyintas) they accompany.

    ``user_id`` is the companion (pendamping) account that owns the profile. It
    is unique because a companion accompanies exactly one survivor, so
    onboarding produces a single profile per account.
    """

    __tablename__ = "survivor_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Nama panggilan penyintas (required).
    name = Column(String(50), nullable=False)

    age_range = Column(String(20), nullable=True)
    primary_language = Column(String(20), nullable=True)
    communication_goals = Column(JSON, nullable=False, default=list)
    instruction_preference = Column(String(30), nullable=True)
    preferred_session_duration = Column(String(10), nullable=True)
    preferred_topics = Column(JSON, nullable=False, default=list)
    practice_mode = Column(String(20), nullable=True)
    personalization_confirmed = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
