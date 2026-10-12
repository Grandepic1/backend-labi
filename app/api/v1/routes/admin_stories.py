from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.models import AuditLog, Session, Story, StoryInformationUnit, StoryVersion, Users
from app.schemas.story import IUCreate, IURead, IUUpdate, StoryCreate, StoryUpdate, StoryVersionRead

router = APIRouter(prefix="/admin/stories", tags=["admin-stories"])


async def _get_story(db: AsyncSession, story_id: int) -> Story:
    story = (await db.execute(select(Story).where(Story.id == story_id))).scalar_one_or_none()
    if story is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
    return story


async def _latest_version(db: AsyncSession, story_id: int) -> StoryVersion | None:
    return (
        await db.execute(
            select(StoryVersion)
            .where(StoryVersion.story_id == story_id)
            .order_by(StoryVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _version_out(v: StoryVersion) -> StoryVersionRead:
    return StoryVersionRead(
        id=v.id,
        story_id=v.story_id,
        version_number=v.version_number,
        title=v.title,
        status=v.status,
        published_at=v.published_at,
        created_at=v.created_at,
    )


def _iu_out(u: StoryInformationUnit) -> IURead:
    return IURead(
        id=u.id,
        code=u.code,
        description=u.description,
        accepted_variants=list(u.accepted_variants or []),
        scoring_rule=u.scoring_rule,
        display_order=u.display_order,
    )


@router.post("", response_model=StoryVersionRead, status_code=status.HTTP_201_CREATED)
async def admin_create_story(
    data: StoryCreate,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> StoryVersionRead:
    slug = data.slug.strip().lower()
    existing = (await db.execute(select(Story).where(Story.slug == slug))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Story slug already exists")
    story = Story(slug=slug, status="draft", created_by=admin.id)
    db.add(story)
    await db.flush()
    version = StoryVersion(
        story_id=story.id,
        version_number=1,
        title=data.title.strip(),
        story_text=data.story_text,
        instructions=data.instructions,
        language=(data.language or "id").strip() or "id",
        estimated_duration_seconds=data.estimated_duration_seconds,
        status="draft",
        created_by=admin.id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return _version_out(version)


@router.put("/{story_id}", response_model=StoryVersionRead)
async def admin_update_story(
    story_id: int,
    data: StoryUpdate,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> StoryVersionRead:
    story = await _get_story(db, story_id)
    if story.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Story is archived")
    if not any([data.title, data.story_text, data.instructions, data.language, data.estimated_duration_seconds is not None]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    latest = await _latest_version(db, story_id)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Story has no versions")
    if latest.status == "draft":
        # Editable in place; carry over IUs untouched.
        if data.title:
            latest.title = data.title.strip()
        if data.story_text:
            latest.story_text = data.story_text
        if data.instructions:
            latest.instructions = data.instructions
        if data.language:
            latest.language = data.language.strip() or "id"
        if data.estimated_duration_seconds is not None:
            latest.estimated_duration_seconds = data.estimated_duration_seconds
        await db.commit()
        await db.refresh(latest)
        return _version_out(latest)

    # Published/retired: freeze history, open a new draft copying content + IUs.
    new_version = StoryVersion(
        story_id=story.id,
        version_number=latest.version_number + 1,
        title=data.title.strip() if data.title else latest.title,
        story_text=data.story_text if data.story_text else latest.story_text,
        instructions=data.instructions if data.instructions else latest.instructions,
        language=(data.language.strip() or latest.language) if data.language else latest.language,
        estimated_duration_seconds=(
            data.estimated_duration_seconds
            if data.estimated_duration_seconds is not None
            else latest.estimated_duration_seconds
        ),
        status="draft",
        created_by=admin.id,
    )
    db.add(new_version)
    await db.flush()
    old_ius = list(
        (
            await db.execute(
                select(StoryInformationUnit).where(
                    StoryInformationUnit.story_version_id == latest.id,
                    StoryInformationUnit.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for u in old_ius:
        db.add(
            StoryInformationUnit(
                story_version_id=new_version.id,
                code=u.code,
                description=u.description,
                scoring_rule=u.scoring_rule,
                accepted_variants=list(u.accepted_variants or []),
                display_order=u.display_order,
                is_active=True,
            )
        )
    story.status = "draft"
    await db.commit()
    await db.refresh(new_version)
    return _version_out(new_version)


@router.post("/{story_id}/ius", response_model=IURead, status_code=status.HTTP_201_CREATED)
async def admin_add_iu(
    story_id: int,
    data: IUCreate,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> IURead:
    await _get_story(db, story_id)
    latest = await _latest_version(db, story_id)
    if latest is None or latest.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No editable draft version; update the story first to open a draft",
        )
    code = data.code.strip()
    dup = (
        await db.execute(
            select(StoryInformationUnit).where(
                StoryInformationUnit.story_version_id == latest.id,
                StoryInformationUnit.code == code,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IU code already exists in this version")
    iu = StoryInformationUnit(
        story_version_id=latest.id,
        code=code,
        description=data.description,
        scoring_rule=data.scoring_rule,
        accepted_variants=list(data.accepted_variants or []),
        display_order=data.display_order,
        is_active=True,
    )
    db.add(iu)
    await db.commit()
    await db.refresh(iu)
    return _iu_out(iu)


@router.put("/{story_id}/ius/{iu_id}", response_model=IURead)
async def admin_update_iu(
    story_id: int,
    iu_id: int,
    data: IUUpdate,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> IURead:
    await _get_story(db, story_id)
    iu = (await db.execute(select(StoryInformationUnit).where(StoryInformationUnit.id == iu_id))).scalar_one_or_none()
    if iu is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IU not found")
    version = (await db.execute(select(StoryVersion).where(StoryVersion.id == iu.story_version_id))).scalar_one_or_none()
    if version is None or version.story_id != story_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IU does not belong to this story")
    if version.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft versions can be edited")
    if data.code and data.code.strip() != iu.code:
        dup = (
            await db.execute(
                select(StoryInformationUnit).where(
                    StoryInformationUnit.story_version_id == version.id,
                    StoryInformationUnit.code == data.code.strip(),
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IU code already exists in this version")
        iu.code = data.code.strip()
    if data.description is not None:
        iu.description = data.description
    if data.scoring_rule is not None:
        iu.scoring_rule = data.scoring_rule
    if data.accepted_variants is not None:
        iu.accepted_variants = list(data.accepted_variants)
    if data.display_order is not None:
        iu.display_order = data.display_order
    await db.commit()
    await db.refresh(iu)
    return _iu_out(iu)


@router.delete("/{story_id}/ius/{iu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_iu(
    story_id: int,
    iu_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> None:
    await _get_story(db, story_id)
    iu = (await db.execute(select(StoryInformationUnit).where(StoryInformationUnit.id == iu_id))).scalar_one_or_none()
    if iu is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IU not found")
    version = (await db.execute(select(StoryVersion).where(StoryVersion.id == iu.story_version_id))).scalar_one_or_none()
    if version is None or version.story_id != story_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IU does not belong to this story")
    if version.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft versions can be edited")
    await db.delete(iu)
    await db.commit()


@router.post("/{story_id}/publish", response_model=StoryVersionRead)
async def admin_publish(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> StoryVersionRead:
    story = await _get_story(db, story_id)
    latest = await _latest_version(db, story_id)
    if latest is None or latest.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No draft version to publish")
    iu_count = (
        await db.execute(
            select(func.count())
            .select_from(StoryInformationUnit)
            .where(
                StoryInformationUnit.story_version_id == latest.id,
                StoryInformationUnit.is_active.is_(True),
            )
        )
    ).scalar_one()
    if not iu_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot publish a version with zero IUs",
        )
    # Retire older published versions; history (sessions) keeps its frozen ref.
    older = list(
        (
            await db.execute(
                select(StoryVersion).where(StoryVersion.story_id == story_id, StoryVersion.status == "published")
            )
        )
        .scalars()
        .all()
    )
    for o in older:
        o.status = "retired"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest.status = "published"
    latest.published_at = now
    story.status = "published"
    db.add(
        AuditLog(
            actor_user_id=admin.id,
            action="story.published",
            entity_type="story_version",
            entity_id=str(latest.id),
            meta={"story_id": story.id, "version": latest.version_number},
        )
    )
    await db.commit()
    await db.refresh(latest)
    return _version_out(latest)


@router.post("/{story_id}/archive", response_model=dict)
async def admin_archive(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Users = Depends(require_admin),
) -> dict:
    story = await _get_story(db, story_id)
    story.status = "archived"
    db.add(
        AuditLog(
            actor_user_id=admin.id,
            action="story.archived",
            entity_type="story",
            entity_id=str(story.id),
            meta={},
        )
    )
    await db.commit()
    return {"id": story.id, "status": "archived"}
