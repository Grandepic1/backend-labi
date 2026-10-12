from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Story, StoryInformationUnit, StoryVersion, Users
from app.schemas.story import IURead, StoryDetail, StoryListItem

router = APIRouter(prefix="/stories", tags=["stories"])


async def _published_version(db: AsyncSession, story_id: int) -> StoryVersion | None:
    stmt = (
        select(StoryVersion)
        .where(StoryVersion.story_id == story_id, StoryVersion.status == "published")
        .order_by(StoryVersion.version_number.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=dict)
async def list_stories(
    status: str = Query(default="published"),
    db: AsyncSession = Depends(get_db),
    _user: Users = Depends(get_current_user),
) -> dict:
    # Caregivers only ever see published stories.
    stories = list(
        (await db.execute(select(Story).where(Story.status == "published").order_by(Story.id))).scalars().all()
    )
    data: list[dict] = []
    for s in stories:
        v = await _published_version(db, s.id)
        if v is None:
            continue
        iu_count = (
            await db.execute(
                select(func.count())
                .select_from(StoryInformationUnit)
                .where(
                    StoryInformationUnit.story_version_id == v.id,
                    StoryInformationUnit.is_active.is_(True),
                )
            )
        ).scalar_one()
        data.append(
            StoryListItem(
                id=s.id,
                title=v.title,
                version=v.version_number,
                estimated_duration_seconds=v.estimated_duration_seconds,
                iu_count=int(iu_count or 0),
            ).model_dump()
        )
    return {"data": data}


@router.get("/{story_id}", response_model=StoryDetail)
async def get_story(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    _user: Users = Depends(get_current_user),
) -> StoryDetail:
    story = (await db.execute(select(Story).where(Story.id == story_id))).scalar_one_or_none()
    if story is None or story.status == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
    version = await _published_version(db, story_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story has no published version")
    ius = list(
        (
            await db.execute(
                select(StoryInformationUnit)
                .where(
                    StoryInformationUnit.story_version_id == version.id,
                    StoryInformationUnit.is_active.is_(True),
                )
                .order_by(StoryInformationUnit.display_order, StoryInformationUnit.id)
            )
        )
        .scalars()
        .all()
    )
    return StoryDetail(
        id=story.id,
        title=version.title,
        version=version.version_number,
        story_text=version.story_text,
        instructions=version.instructions,
        ius=[
            IURead(
                id=u.id,
                code=u.code,
                description=u.description,
                accepted_variants=list(u.accepted_variants or []),
                scoring_rule=u.scoring_rule,
                display_order=u.display_order,
            )
            for u in ius
        ],
    )
