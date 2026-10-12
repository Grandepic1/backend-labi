from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_admin
from app.core.database import get_db
from app.models import Participant, Users
from app.schemas.participant import ParticipantCreate, ParticipantRead

router = APIRouter(prefix="/participants", tags=["participants"])


@router.post("", response_model=ParticipantRead, status_code=status.HTTP_201_CREATED)
async def create_participant(
    data: ParticipantCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Participant:
    p = Participant(
        display_name=data.display_name.strip(),
        date_of_birth=data.date_of_birth,
        preferred_language=(data.preferred_language or "id").strip() or "id",
        created_by=current_user.id,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.get("", response_model=list[ParticipantRead])
async def list_participants(
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> list[Participant]:
    stmt = select(Participant).where(Participant.archived_at.is_(None)).order_by(Participant.id.desc()).limit(200)
    if not is_admin(current_user):
        stmt = stmt.where(Participant.created_by == current_user.id)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{participant_id}", response_model=ParticipantRead)
async def get_participant(
    participant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Participant:
    p = (await db.execute(select(Participant).where(Participant.id == participant_id))).scalar_one_or_none()
    if p is None or p.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    if not is_admin(current_user) and p.created_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this participant")
    return p
