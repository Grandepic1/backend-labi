from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import SurvivorProfiles, Users
from app.schemas.survivor_profile import (
    SurvivorProfileRead,
    SurvivorProfileUpsert,
)

router = APIRouter(prefix="/me", tags=["survivor-profile"])


async def _get_profile(db: AsyncSession, user_id: int) -> SurvivorProfiles | None:
    """Return the survivor profile owned by this companion, if any."""
    return (
        await db.execute(
            select(SurvivorProfiles).where(SurvivorProfiles.user_id == user_id)
        )
    ).scalar_one_or_none()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Survivor profile not found",
    )


@router.get("/survivor-profile", response_model=SurvivorProfileRead)
async def read_survivor_profile(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SurvivorProfiles:
    """Get the survivor profile created during personalization.

    Returns 404 until the companion completes onboarding, which the app uses
    to decide whether to show the personalization screen.
    """
    profile = await _get_profile(db, current_user.id)
    if profile is None:
        raise _not_found()
    return profile


@router.put("/survivor-profile", response_model=SurvivorProfileRead)
async def upsert_survivor_profile(
    data: SurvivorProfileUpsert,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SurvivorProfiles:
    """Create or replace the survivor profile (idempotent onboarding submit)."""
    profile = await _get_profile(db, current_user.id)
    if profile is None:
        profile = SurvivorProfiles(user_id=current_user.id)
        db.add(profile)

    # mode="json" turns the str enums into their plain values so the JSON
    # columns stay JSON-serializable and the varchar columns get strings.
    for field, value in data.model_dump(mode="json").items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/survivor-profile", status_code=status.HTTP_204_NO_CONTENT)
async def delete_survivor_profile(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the survivor profile so personalization runs again."""
    profile = await _get_profile(db, current_user.id)
    if profile is None:
        raise _not_found()
    await db.delete(profile)
    await db.commit()
