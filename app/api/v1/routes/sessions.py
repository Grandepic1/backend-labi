from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_admin
from app.core.database import get_db
from app.models import (
    AuditLog,
    Participant,
    Recording,
    Session,
    SessionAssessment,
    SessionAssessmentItem,
    Story,
    StoryInformationUnit,
    StoryVersion,
    Transcript,
    Users,
)
from app.schemas.assessment import (
    AssessmentRead,
    AssessmentUpsert,
    CompleteIn,
    CompleteOut,
    CompleteResult,
    ResultItemRead,
    ResultRead,
)
from app.schemas.session import (
    PaginatedSessions,
    RecordingRead,
    SessionCreate,
    SessionHistoryItem,
    SessionRead,
    TranscriptRead,
    TranscriptUpsert,
)
from app.services.scoring import (
    SESSION_ASSESSMENT_IN_PROGRESS,
    SESSION_CANCELLED,
    SESSION_COMPLETED,
    SESSION_CREATED,
    SESSION_RECORDING_UPLOADED,
    TASK_IMMEDIATE_RECALL,
    iu_recall_percent,
    summarize_statuses,
)
from app.services.storage import resolve_path, save_upload

router = APIRouter(tags=["sessions"])


# --- helpers ---


async def _get_session(db: AsyncSession, session_id: int) -> Session | None:
    return (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()


def _check_session_access(session: Session, user: Users) -> None:
    if is_admin(user):
        return
    if session.caregiver_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this session")


async def _require_session(db: AsyncSession, session_id: int, user: Users) -> Session:
    session = await _get_session(db, session_id)
    # Hide existence from unauthorized users.
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    _check_session_access(session, user)
    return session


async def _published_version(db: AsyncSession, story_id: int) -> StoryVersion | None:
    return (
        await db.execute(
            select(StoryVersion)
            .where(StoryVersion.story_id == story_id, StoryVersion.status == "published")
            .order_by(StoryVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _active_ius(db: AsyncSession, version_id: int) -> list[StoryInformationUnit]:
    return list(
        (
            await db.execute(
                select(StoryInformationUnit)
                .where(
                    StoryInformationUnit.story_version_id == version_id,
                    StoryInformationUnit.is_active.is_(True),
                )
                .order_by(StoryInformationUnit.display_order, StoryInformationUnit.id)
            )
        )
        .scalars()
        .all()
    )


async def _get_recording(db: AsyncSession, session_id: int) -> Recording | None:
    return (
        await db.execute(
            select(Recording).where(Recording.session_id == session_id, Recording.deleted_at.is_(None))
        )
    ).scalar_one_or_none()


def _parse_opt_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- POST /sessions ---


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Session:
    if data.task_type != TASK_IMMEDIATE_RECALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"task_type must be '{TASK_IMMEDIATE_RECALL}' in MVP",
        )
    participant = (await db.execute(select(Participant).where(Participant.id == data.participant_id))).scalar_one_or_none()
    if participant is None or participant.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    if not is_admin(current_user) and participant.created_by not in (None, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to use this participant")

    story = (await db.execute(select(Story).where(Story.id == data.story_id))).scalar_one_or_none()
    if story is None or story.status != "published":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Story has no published version available for new sessions",
        )
    version = await _published_version(db, story.id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Story has no published version available for new sessions",
        )
    ius = await _active_ius(db, version.id)
    if not ius:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Story version has no IUs and cannot be scored",
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = Session(
        participant_id=participant.id,
        story_id=story.id,
        story_version_id=version.id,
        caregiver_id=current_user.id,
        task_type=data.task_type,
        status=SESSION_CREATED,
        session_note=data.session_note,
        started_at=now,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Session:
    return await _require_session(db, session_id, current_user)


@router.post("/sessions/{session_id}/cancel", response_model=SessionRead)
async def cancel_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Session:
    session = await _require_session(db, session_id, current_user)
    if session.status == SESSION_COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already completed")
    if session.status == SESSION_CANCELLED:
        return session
    session.status = SESSION_CANCELLED
    session.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(session)
    return session


# --- history ---


@router.get("/sessions", response_model=PaginatedSessions)
async def list_sessions(
    participant_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> PaginatedSessions:
    stmt = select(Session).order_by(Session.created_at.desc(), Session.id.desc())
    count_stmt = select(func.count()).select_from(Session)
    if not is_admin(current_user):
        stmt = stmt.where(Session.caregiver_id == current_user.id)
        count_stmt = count_stmt.where(Session.caregiver_id == current_user.id)
    if participant_id is not None:
        stmt = stmt.where(Session.participant_id == participant_id)
        count_stmt = count_stmt.where(Session.participant_id == participant_id)
    if status_filter:
        stmt = stmt.where(Session.status == status_filter)
        count_stmt = count_stmt.where(Session.status == status_filter)

    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    sessions = list((await db.execute(stmt.offset(offset).limit(page_size))).scalars().all())

    items: list[SessionHistoryItem] = []
    for s in sessions:
        version = (await db.execute(select(StoryVersion).where(StoryVersion.id == s.story_version_id))).scalar_one_or_none()
        rec = await _get_recording(db, s.id)
        assessment = (
            await db.execute(select(SessionAssessment).where(SessionAssessment.session_id == s.id))
        ).scalar_one_or_none()
        pct = float(assessment.iu_recall_percent) if assessment and assessment.iu_recall_percent is not None else None
        items.append(
            SessionHistoryItem(
                id=s.id,
                participant_id=s.participant_id,
                story_title=version.title if version else None,
                story_version=version.version_number if version else None,
                status=s.status,
                iu_recall_percent=pct,
                completed_at=s.completed_at,
                has_recording=rec is not None,
            )
        )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedSessions(
        data=items,
        pagination={"page": page, "page_size": page_size, "total_items": total, "total_pages": total_pages},
    )


# --- recording upload/playback ---


@router.post("/sessions/{session_id}/recording", response_model=RecordingRead, status_code=status.HTTP_201_CREATED)
async def upload_recording(
    session_id: int,
    file: UploadFile = File(...),
    duration_ms: int | None = Form(default=None),
    recorded_at: str | None = Form(default=None),
    transcript_text: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> RecordingRead:
    session = await _require_session(db, session_id, current_user)
    if session.status in (SESSION_COMPLETED, SESSION_CANCELLED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already finalized or cancelled")
    existing = await _get_recording(db, session_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recording already exists; replacement must be explicit",
        )
    try:
        saved = await save_upload(file, session_id)
    except ValueError as e:
        code = str(e)
        if code == "TOO_LARGE":
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds size limit")
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported audio format")

    rec = Recording(
        session_id=session.id,
        storage_provider="local_private",
        storage_key=saved["storage_key"],
        original_filename=file.filename[:255] if file.filename else None,
        mime_type=saved["mime_type"],
        file_size_bytes=saved["file_size_bytes"],
        duration_ms=duration_ms,
        checksum_sha256=saved["checksum_sha256"],
        recorded_at=_parse_opt_datetime(recorded_at),
        uploaded_by=current_user.id,
    )
    db.add(rec)
    session.status = SESSION_RECORDING_UPLOADED
    await db.flush()

    if transcript_text and transcript_text.strip():
        db.add(
            Transcript(
                session_id=session.id,
                recording_id=rec.id,
                text=transcript_text.strip(),
                source="manual",
                review_status="draft",
                created_by=current_user.id,
            )
        )
    await db.commit()
    await db.refresh(rec)
    return RecordingRead(
        id=rec.id,
        session_id=session.id,
        storage_status="stored",
        duration_ms=rec.duration_ms,
        mime_type=rec.mime_type,
        file_size_bytes=rec.file_size_bytes,
        created_at=rec.created_at,
        playback_url=f"/api/v1/sessions/{session.id}/recording",
    )


@router.get("/sessions/{session_id}/recording")
async def download_recording(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    session = await _require_session(db, session_id, current_user)
    rec = await _get_recording(db, session_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    try:
        path = resolve_path(rec.storage_key)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Recording storage error")
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file missing")
    # Never log the path/key.
    return FileResponse(path, media_type=rec.mime_type, filename=f"session-{session.id}-recording")


# --- transcripts ---


@router.post("/sessions/{session_id}/transcript", response_model=TranscriptRead, status_code=status.HTTP_201_CREATED)
async def upsert_transcript(
    session_id: int,
    data: TranscriptUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Transcript:
    session = await _require_session(db, session_id, current_user)
    if session.status in (SESSION_COMPLETED, SESSION_CANCELLED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already finalized or cancelled")
    rec = await _get_recording(db, session_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Upload a recording first")
    if data.source not in ("manual", "asr"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source must be 'manual' or 'asr'")
    if data.review_status not in ("draft", "reviewed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="review_status must be 'draft' or 'reviewed'")
    t = Transcript(
        session_id=session.id,
        recording_id=rec.id,
        text=data.text.strip(),
        source=data.source,
        review_status=data.review_status,
        created_by=current_user.id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@router.get("/sessions/{session_id}/transcript", response_model=TranscriptRead)
async def get_transcript(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> Transcript:
    await _require_session(db, session_id, current_user)
    t = (
        await db.execute(
            select(Transcript).where(Transcript.session_id == session_id).order_by(Transcript.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")
    return t


# --- assessment draft ---


@router.put("/sessions/{session_id}/assessment", response_model=AssessmentRead)
async def put_assessment(
    session_id: int,
    data: AssessmentUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> AssessmentRead:
    session = await _require_session(db, session_id, current_user)
    if session.status in (SESSION_COMPLETED, SESSION_CANCELLED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already finalized or cancelled")
    rec = await _get_recording(db, session_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Upload a recording before assessing")

    iu_ids = [i.iu_id for i in data.items]
    if len(set(iu_ids)) != len(iu_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate iu_id in request")

    valid_ius = await _active_ius(db, session.story_version_id)
    valid_ids = {u.id for u in valid_ius}
    for i in data.items:
        if i.iu_id not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"IU {i.iu_id} does not belong to this session's story version",
            )

    met, not_met, unclear = summarize_statuses([i.status for i in data.items])
    total = len(valid_ius)
    pct = iu_recall_percent(met, total)

    assessment = (
        await db.execute(select(SessionAssessment).where(SessionAssessment.session_id == session.id))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if assessment is None:
        assessment = SessionAssessment(
            session_id=session.id,
            assessor_id=current_user.id,
            status="draft",
            total_iu=total,
            met_count=met,
            not_met_count=not_met,
            unclear_count=unclear,
            iu_recall_percent=pct,
        )
        db.add(assessment)
        await db.flush()
    else:
        if assessment.status == "final":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Assessment already finalized")
        assessment.assessor_id = current_user.id
        assessment.total_iu = total
        assessment.met_count = met
        assessment.not_met_count = not_met
        assessment.unclear_count = unclear
        assessment.iu_recall_percent = pct
        assessment.updated_at = now
        await db.execute(
            SessionAssessmentItem.__table__.delete().where(SessionAssessmentItem.assessment_id == assessment.id)
        )

    for i in data.items:
        db.add(
            SessionAssessmentItem(
                assessment_id=assessment.id,
                iu_id=i.iu_id,
                status=i.status,
                evidence_note=(i.evidence_note.strip()[:2000] if i.evidence_note else None),
                assessed_at=now,
            )
        )
    if session.status in (SESSION_CREATED, SESSION_RECORDING_UPLOADED):
        session.status = SESSION_ASSESSMENT_IN_PROGRESS
    await db.commit()
    await db.refresh(assessment)
    return AssessmentRead(
        session_id=session.id,
        assessment_status="in_progress",
        met_count=met,
        not_met_count=not_met,
        unclear_count=unclear,
        total_iu=total,
        provisional_recall_percent=float(pct) if pct is not None else None,
        is_final=False,
        updated_at=assessment.updated_at,
    )


# --- finalize ---


@router.post("/sessions/{session_id}/complete", response_model=CompleteOut)
async def complete_session(
    session_id: int,
    data: CompleteIn,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> CompleteOut:
    if not data.confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm must be true to finalize")
    session = await _require_session(db, session_id, current_user)
    if session.status == SESSION_COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already completed")
    if session.status == SESSION_CANCELLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is cancelled")
    rec = await _get_recording(db, session_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ASSESSMENT_INCOMPLETE: no recording")

    assessment = (
        await db.execute(select(SessionAssessment).where(SessionAssessment.session_id == session.id))
    ).scalar_one_or_none()
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ASSESSMENT_INCOMPLETE: no assessment")

    items = list(
        (await db.execute(select(SessionAssessmentItem).where(SessionAssessmentItem.assessment_id == assessment.id)))
        .scalars()
        .all()
    )
    valid_ius = await _active_ius(db, session.story_version_id)
    total = len(valid_ius)
    if total == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Story version has no IUs")
    assessed_ids = {it.iu_id for it in items}
    missing = len(valid_ius) - len(assessed_ids)
    unclear = sum(1 for it in items if it.status == "unclear")
    if missing > 0 or unclear > 0 or len(items) != total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ASSESSMENT_INCOMPLETE",
                "message": "All IUs must be met/not_met before finalizing",
                "details": {"unassessed_iu_count": max(0, missing), "unclear_iu_count": unclear},
            },
        )

    met = sum(1 for it in items if it.status == "met")
    not_met = sum(1 for it in items if it.status == "not_met")
    pct: Decimal | None = iu_recall_percent(met, total)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assessment.status = "final"
    assessment.assessor_id = current_user.id
    assessment.total_iu = total
    assessment.met_count = met
    assessment.not_met_count = not_met
    assessment.unclear_count = 0
    assessment.iu_recall_percent = pct
    assessment.finalized_at = now
    session.status = SESSION_COMPLETED
    session.completed_at = now
    db.add(
        AuditLog(
            actor_user_id=current_user.id,
            action="session.completed",
            entity_type="session",
            entity_id=str(session.id),
            meta={"met_count": met, "total_iu": total},
        )
    )
    await db.commit()
    await db.refresh(session)
    return CompleteOut(
        session_id=session.id,
        status=SESSION_COMPLETED,
        result=CompleteResult(
            met_count=met, not_met_count=not_met, total_iu=total, iu_recall_percent=float(pct or 0)
        ),
        completed_at=session.completed_at,
    )


# --- result ---


@router.get("/sessions/{session_id}/result", response_model=ResultRead)
async def get_result(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> ResultRead:
    session = await _require_session(db, session_id, current_user)
    assessment = (
        await db.execute(select(SessionAssessment).where(SessionAssessment.session_id == session.id))
    ).scalar_one_or_none()
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No assessment for this session")
    items = list(
        (await db.execute(select(SessionAssessmentItem).where(SessionAssessmentItem.assessment_id == assessment.id)))
        .scalars()
        .all()
    )
    iu_map = {u.id: u for u in await _active_ius(db, session.story_version_id)}
    version = (await db.execute(select(StoryVersion).where(StoryVersion.id == session.story_version_id))).scalar_one_or_none()
    rec = await _get_recording(db, session.id)
    return ResultRead(
        session_id=session.id,
        status=session.status,
        met_count=assessment.met_count,
        not_met_count=assessment.not_met_count,
        unclear_count=assessment.unclear_count,
        total_iu=assessment.total_iu,
        iu_recall_percent=float(assessment.iu_recall_percent) if assessment.iu_recall_percent is not None else None,
        story_id=session.story_id,
        story_version_id=session.story_version_id,
        story_title=version.title if version else "",
        assessor_id=assessment.assessor_id,
        completed_at=session.completed_at,
        has_recording=rec is not None,
        items=[
            ResultItemRead(
                iu_id=it.iu_id,
                code=iu_map[it.iu_id].code if it.iu_id in iu_map else str(it.iu_id),
                description=iu_map[it.iu_id].description if it.iu_id in iu_map else "",
                status=it.status,
                evidence_note=it.evidence_note,
            )
            for it in sorted(items, key=lambda x: iu_map[x.iu_id].display_order if x.iu_id in iu_map else 0)
        ],
    )
