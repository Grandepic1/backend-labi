import logging
import math
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_admin
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.models import (
    AuditLog,
    Participant,
    Recording,
    Session,
    SessionAnalysisRun,
    SessionAssessment,
    SessionAssessmentItem,
    SessionIuSuggestion,
    SessionSilentPause,
    SessionSpeechMetrics,
    SessionTrainingLog,
    SessionTrainingRecommendation,
    Story,
    StoryInformationUnit,
    StoryVersion,
    Transcript,
    SurvivorProfiles,
    Users,
)
from app.schemas.analysis import (
    AnalysisRead,
    AnalysisRunIn,
    IuSuggestionRead,
    SilentPauseRead,
    SpeechMetricsRead,
)
from app.schemas.training import (
    ActionableGuidanceRead,
    SessionTrainingRecommendationRead,
    TrainingLogCreate,
    TrainingLogRead,
)
from app.schemas.assessment import (
    AssessmentItemIn,
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
from app.services import ai as ai_service
from app.services import asr as asr_service
from app.services.audio import AudioToolFailed, AudioToolMissing, detect_silences, probe_duration_ms
from app.services.scoring import (
    IU_STATUSES,
    SESSION_ASSESSMENT_IN_PROGRESS,
    SESSION_CANCELLED,
    SESSION_COMPLETED,
    SESSION_CREATED,
    SESSION_RECORDING_UPLOADED,
    TASK_IMMEDIATE_RECALL,
    iu_recall_percent,
    summarize_statuses,
)
from app.services.speech_metrics import (
    EDGE_TOLERANCE_MS,
    compute_log_pause_metrics,
    compute_speech_metrics,
    internal_pauses,
)
from app.services.storage import resolve_path, save_upload

router = APIRouter(tags=["sessions"])

logger = logging.getLogger("app.analysis")


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


async def _latest_transcript(db: AsyncSession, session_id: int) -> Transcript | None:
    return (
        await db.execute(
            select(Transcript).where(Transcript.session_id == session_id).order_by(Transcript.id.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def _latest_completed_run(db: AsyncSession, session_id: int) -> SessionAnalysisRun | None:
    return (
        await db.execute(
            select(SessionAnalysisRun)
            .where(SessionAnalysisRun.session_id == session_id, SessionAnalysisRun.status == "completed")
            .order_by(SessionAnalysisRun.created_at.desc(), SessionAnalysisRun.id.desc())
            .limit(1)
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


async def _apply_assessment(
    db: AsyncSession, session: Session, user: Users, items: list[AssessmentItemIn]
) -> AssessmentRead:
    if session.status in (SESSION_COMPLETED, SESSION_CANCELLED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already finalized or cancelled")
    rec = await _get_recording(db, session.id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Upload a recording before assessing")

    iu_ids = [i.iu_id for i in items]
    if len(set(iu_ids)) != len(iu_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate iu_id in request")

    valid_ius = await _active_ius(db, session.story_version_id)
    valid_ids = {u.id for u in valid_ius}
    for i in items:
        if i.iu_id not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"IU {i.iu_id} does not belong to this session's story version",
            )

    met, not_met, unclear = summarize_statuses([i.status for i in items])
    total = len(valid_ius)
    pct = iu_recall_percent(met, total)

    assessment = (
        await db.execute(select(SessionAssessment).where(SessionAssessment.session_id == session.id))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if assessment is None:
        assessment = SessionAssessment(
            session_id=session.id,
            assessor_id=user.id,
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
        assessment.assessor_id = user.id
        assessment.total_iu = total
        assessment.met_count = met
        assessment.not_met_count = not_met
        assessment.unclear_count = unclear
        assessment.iu_recall_percent = pct
        assessment.updated_at = now
        await db.execute(
            SessionAssessmentItem.__table__.delete().where(SessionAssessmentItem.assessment_id == assessment.id)
        )

    for i in items:
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


# --- assessment draft ---


@router.put("/sessions/{session_id}/assessment", response_model=AssessmentRead)
async def put_assessment(
    session_id: int,
    data: AssessmentUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> AssessmentRead:
    session = await _require_session(db, session_id, current_user)
    return await _apply_assessment(db, session, current_user, data.items)


@router.post("/sessions/{session_id}/assessment/from-suggestions", response_model=AssessmentRead)
async def assessment_from_suggestions(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> AssessmentRead:
    session = await _require_session(db, session_id, current_user)
    run = await _latest_completed_run(db, session.id)
    suggestions = (
        list(
            (
                await db.execute(select(SessionIuSuggestion).where(SessionIuSuggestion.run_id == run.id))
            )
            .scalars()
            .all()
        )
        if run is not None
        else []
    )
    valid_ius = await _active_ius(db, session.story_version_id)
    by_iu = {s.iu_id: s for s in suggestions if s.suggested_status in IU_STATUSES}
    # Checked before any write: partial coverage must not touch the draft.
    if not valid_ius or any(u.id not in by_iu for u in valid_ius):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No complete IU suggestions for this session",
        )
    items = [
        AssessmentItemIn(iu_id=u.id, status=by_iu[u.id].suggested_status, evidence_note=by_iu[u.id].evidence_quote)
        for u in valid_ius
    ]
    return await _apply_assessment(db, session, current_user, items)


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


# --- analysis: transcription + speech metrics + IU suggestions ---


# Every failure mode is mapped to a stable code on the run row.
_ERROR_CODES: dict[type[BaseException], str] = {
    asr_service.AsrModelUnavailable: "ASR_MODEL_UNAVAILABLE",
    asr_service.AsrTimeout: "ASR_TIMEOUT",
    asr_service.AsrFailed: "ASR_FAILED",
    AudioToolMissing: "FFMPEG_MISSING",
    AudioToolFailed: "FFMPEG_FAILED",
    ai_service.AiNotConfigured: "AI_NOT_CONFIGURED",
    ai_service.AiRequestFailed: "AI_REQUEST_FAILED",
    ai_service.AiInvalidOutput: "AI_INVALID_OUTPUT",
}


class _RunAborted(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error_code_for(exc: BaseException) -> str:
    if isinstance(exc, _RunAborted):
        return exc.code
    for exc_type, code in _ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "INTERNAL"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _store_speech_metrics(db: AsyncSession, session_id: int, run_id: int, path) -> None:
    duration_ms = await probe_duration_ms(path)
    silences = await detect_silences(path, duration_ms=duration_ms)
    transcript = await _latest_transcript(db, session_id)
    computed = compute_speech_metrics(
        file_duration_ms=duration_ms,
        silences=silences,
        transcript_text=transcript.text if transcript is not None else None,
        filled_pause_tokens=settings.filled_pause_token_set,
    )
    computed.pop("silent_pause_durations_ms")
    log_metrics = computed.pop("log_metrics", {})
    db.add(
        SessionSpeechMetrics(
            session_id=session_id,
            run_id=run_id,
            params={
                "noise_db": settings.PAUSE_NOISE_DB,
                "min_pause_ms": settings.PAUSE_MIN_MS,
                "edge_tolerance_ms": EDGE_TOLERANCE_MS,
                "ffmpeg": settings.FFMPEG_BIN,
                "ffprobe": settings.FFPROBE_BIN,
                "filled_pause_tokens": sorted(settings.filled_pause_token_set),
                "log_metrics": {k: float(v) if v is not None else None for k, v in log_metrics.items()},
            },
            **computed,
        )
    )
    # Raw intervals are stored so thresholds can be re-applied later.
    for ordinal, (start_ms, end_ms) in enumerate(internal_pauses(duration_ms, silences), start=1):
        db.add(
            SessionSilentPause(
                run_id=run_id,
                session_id=session_id,
                ordinal=ordinal,
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=end_ms - start_ms,
            )
        )


async def _store_iu_suggestions(db: AsyncSession, session: Session, run: SessionAnalysisRun) -> None:
    transcript = await _latest_transcript(db, session.id)
    if transcript is None or not transcript.text.strip():
        raise _RunAborted("NO_TRANSCRIPT", "no transcript available for IU suggestions")
    version = (
        await db.execute(select(StoryVersion).where(StoryVersion.id == session.story_version_id))
    ).scalar_one_or_none()
    ius = await _active_ius(db, session.story_version_id)
    payload = [
        {
            "code": u.code,
            "description": u.description,
            "scoring_rule": u.scoring_rule,
            "accepted_variants": u.accepted_variants or [],
        }
        for u in ius
    ]
    suggestions = await ai_service.suggest_iu_statuses(
        story_text=version.story_text if version is not None else "",
        ius=payload,
        transcript=transcript.text,
    )
    by_code = {u.code: u.id for u in ius}
    for entry in suggestions:
        iu_id = by_code.get(entry["code"])
        if iu_id is None:
            raise ai_service.AiInvalidOutput(f"IU code tidak dikenal: {entry['code']}")
        db.add(
            SessionIuSuggestion(
                run_id=run.id,
                session_id=session.id,
                iu_id=iu_id,
                suggested_status=entry["status"],
                evidence_quote=entry["evidence_quote"],
                rationale=entry["rationale"],
            )
        )


async def _get_participant_baseline_recall(
    db: AsyncSession, participant_id: int, current_session_id: int
) -> float | None:
    baseline_session = (
        await db.execute(
            select(Session)
            .where(
                Session.participant_id == participant_id,
                Session.status == SESSION_COMPLETED,
                Session.id != current_session_id,
            )
            .order_by(Session.completed_at.asc(), Session.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if baseline_session is None:
        return None
    assessment = (
        await db.execute(
            select(SessionAssessment).where(
                SessionAssessment.session_id == baseline_session.id,
                SessionAssessment.status == "final",
            )
        )
    ).scalar_one_or_none()
    if assessment is None or assessment.iu_recall_percent is None:
        return None
    return float(assessment.iu_recall_percent)

async def _get_survivor_profile_dict(db: AsyncSession, caregiver_id: int) -> dict | None:
    profile = (
        await db.execute(
            select(SurvivorProfiles).where(SurvivorProfiles.user_id == caregiver_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        return None
    return {
        "name": profile.name,
        "primary_language": profile.primary_language,
        "preferred_topics": profile.preferred_topics or [],
        "instruction_preference": profile.instruction_preference,
        "preferred_session_duration": profile.preferred_session_duration,
        "practice_mode": profile.practice_mode,
    }


async def _execute_run(run_id: int, session_id: int, data: AnalysisRunIn) -> None:
    async with AsyncSessionLocal() as db:
        steps: list[str] = []
        try:
            run = (
                await db.execute(select(SessionAnalysisRun).where(SessionAnalysisRun.id == run_id))
            ).scalar_one_or_none()
            session = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
            if run is None or session is None:
                raise _RunAborted("INTERNAL", "analysis run or session missing")
            rec = await _get_recording(db, session_id)
            if rec is None:
                raise _RunAborted("INTERNAL", "recording missing")
            try:
                path = resolve_path(rec.storage_key)
            except ValueError as exc:
                raise _RunAborted("INTERNAL", "recording storage error") from exc
            if not path.is_file():
                raise _RunAborted("INTERNAL", "recording file missing")

            if data.run_transcription:
                steps.append("transcription")
                text = await asr_service.transcribe(path)
                # Append-only: never overwrite a previous transcript.
                db.add(
                    Transcript(
                        session_id=session.id,
                        recording_id=rec.id,
                        text=text,
                        source="asr",
                        review_status="draft",
                        created_by=run.created_by,
                    )
                )
                await db.flush()

            if data.run_speech_metrics:
                steps.append("speech_metrics")
                await _store_speech_metrics(db, session.id, run.id, path)

            if data.run_iu_suggestions:
                steps.append("iu_suggestions")
                await _store_iu_suggestions(db, session, run)

            # If speech metrics were produced, build & store evidence-based guidance in metrics.params
            metrics = (
                await db.execute(
                    select(SessionSpeechMetrics)
                    .where(SessionSpeechMetrics.run_id == run.id)
                    .order_by(SessionSpeechMetrics.created_at.desc(), SessionSpeechMetrics.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if metrics is not None:
                suggestions = list(
                    (
                        await db.execute(
                            select(SessionIuSuggestion, StoryInformationUnit)
                            .join(StoryInformationUnit, StoryInformationUnit.id == SessionIuSuggestion.iu_id)
                            .where(SessionIuSuggestion.run_id == run.id)
                        )
                    ).all()
                )
                iu_results = [
                    {"code": iu.code, "suggested_status": sugg.suggested_status}
                    for sugg, iu in suggestions
                ]
                baseline_recall = await _get_participant_baseline_recall(db, session.participant_id, session.id)
                trend_deltas = None
                if baseline_recall is not None and iu_results:
                    met_count = sum(1 for u in iu_results if u["suggested_status"] == "met")
                    total_iu = len(iu_results)
                    curr_recall = (met_count / total_iu * 100) if total_iu > 0 else None
                    if curr_recall is not None:
                        trend_deltas = {"iu_recall_percent": round(curr_recall - baseline_recall, 2)}

                survivor_profile_dict = await _get_survivor_profile_dict(db, session.caregiver_id)
                guidance = ai_service.build_actionable_guidance(
                    speech_metrics={
                        "speech_rate": float(metrics.speech_rate) if metrics.speech_rate is not None else None,
                        "articulation_rate": float(metrics.articulation_rate) if metrics.articulation_rate is not None else None,
                        "pause_rate_per_100_words": float(metrics.pause_rate_per_100_words) if metrics.pause_rate_per_100_words is not None else None,
                        "silent_pause_total_ms": metrics.silent_pause_total_ms,
                        "silent_pause_count": metrics.silent_pause_count,
                    },
                    iu_results=iu_results,
                    trend_deltas=trend_deltas,
                    survivor_profile=survivor_profile_dict,
                )
                params = dict(metrics.params or {})
                params["actionable_guidance"] = guidance
                metrics.params = params

                db.add(
                    SessionTrainingRecommendation(
                        session_id=session.id,
                        run_id=run.id,
                        participant_id=session.participant_id,
                        urgency_level=guidance.get("urgency_level", "routine"),
                        primary_mode=guidance.get("primary_mode", "cst"),
                        secondary_mode=guidance.get("secondary_mode"),
                        target_goal=guidance.get("target_goal", ""),
                        overall_interpretation=guidance.get("overall_interpretation", ""),
                        medical_alert=guidance.get("medical_alert"),
                        home_trainings=guidance.get("home_trainings", []),
                    )
                )

            run.status = "completed"
            run.finished_at = _now()
            db.add(
                AuditLog(
                    actor_user_id=run.created_by,
                    action="session.analysis_run",
                    entity_type="session",
                    entity_id=str(session.id),
                    # Never the transcript text, just the run summary.
                    meta={"run_id": run.id, "steps": steps},
                )
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — recorded, never raised
            code = _error_code_for(exc)
            logger.exception("analysis run %s failed (%s): %s", run_id, code, exc)
            # Single-transaction run: this discards every uncommitted row,
            # so a failed run leaves no partial artifacts behind.
            await db.rollback()
            failed = (
                await db.execute(select(SessionAnalysisRun).where(SessionAnalysisRun.id == run_id))
            ).scalar_one_or_none()
            if failed is None:
                return
            failed.status = "failed"
            failed.error_code = code
            failed.error_message = (str(exc).strip() or type(exc).__name__)[:500]
            failed.finished_at = _now()
            await db.commit()


async def _load_analysis_read(db: AsyncSession, run: SessionAnalysisRun) -> AnalysisRead:
    metrics = (
        await db.execute(
            select(SessionSpeechMetrics)
            .where(SessionSpeechMetrics.run_id == run.id)
            .order_by(SessionSpeechMetrics.created_at.desc(), SessionSpeechMetrics.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    pauses = list(
        (
            await db.execute(
                select(SessionSilentPause)
                .where(SessionSilentPause.run_id == run.id)
                .order_by(SessionSilentPause.ordinal, SessionSilentPause.id)
            )
        )
        .scalars()
        .all()
    )
    suggestion_rows = (
        await db.execute(
            select(SessionIuSuggestion, StoryInformationUnit)
            .join(StoryInformationUnit, StoryInformationUnit.id == SessionIuSuggestion.iu_id)
            .where(SessionIuSuggestion.run_id == run.id)
            .order_by(StoryInformationUnit.display_order, StoryInformationUnit.id)
        )
    ).all()
    # Same "latest wins" convention as GET .../transcript.
    transcript = await _latest_transcript(db, run.session_id)

    speech: SpeechMetricsRead | None = None
    if metrics is not None:
        pause_durations = [p.duration_ms for p in pauses]
        log_metrics = (metrics.params or {}).get("log_metrics") if metrics.params else None
        if not log_metrics and pause_durations:
            computed_logs = compute_log_pause_metrics(pause_durations)
            log_metrics = {k: float(v) if v is not None else None for k, v in computed_logs.items()}
        elif not log_metrics:
            log_metrics = {}

        speech = SpeechMetricsRead(
            run_id=metrics.run_id,
            session_id=metrics.session_id,
            analysis_method=metrics.analysis_method,
            file_duration_ms=metrics.file_duration_ms,
            lead_silence_ms=metrics.lead_silence_ms,
            tail_silence_ms=metrics.tail_silence_ms,
            speech_duration_ms=metrics.speech_duration_ms,
            phonation_ms=metrics.phonation_ms,
            silent_pause_total_ms=metrics.silent_pause_total_ms,
            silent_pause_count=metrics.silent_pause_count,
            silent_pause_mean_ms=metrics.silent_pause_mean_ms,
            silent_pause_median_ms=metrics.silent_pause_median_ms,
            silent_pause_sd_ms=metrics.silent_pause_sd_ms,
            silent_pause_mean_log=log_metrics.get("mean"),
            silent_pause_median_log=log_metrics.get("median"),
            silent_pause_sd_log=log_metrics.get("sd"),
            silent_pause_total_log=log_metrics.get("total"),
            speech_rate=metrics.speech_rate,
            articulation_rate=metrics.articulation_rate,
            speech_rate_wpm=metrics.speech_rate_wpm,
            articulation_rate_wpm=metrics.articulation_rate_wpm,
            pause_rate_per_100_words=metrics.pause_rate_per_100_words,
            syllable_count=metrics.syllable_count,
            word_count=metrics.word_count,
            filled_pause_count=metrics.filled_pause_count,
            quality_flag=metrics.quality_flag,
            silent_pauses=[
                SilentPauseRead(
                    ordinal=p.ordinal,
                    start_ms=p.start_ms,
                    end_ms=p.end_ms,
                    duration_ms=p.duration_ms,
                    duration_log=round(math.log(p.duration_ms), 2) if p.duration_ms > 0 else None,
                )
                for p in pauses
            ],
            silent_pause_durations_ms=pause_durations,
            created_at=metrics.created_at,
        )

    actionable_guidance: ActionableGuidanceRead | None = None
    rec = (
        await db.execute(
            select(SessionTrainingRecommendation)
            .where(SessionTrainingRecommendation.run_id == run.id)
            .order_by(SessionTrainingRecommendation.id.desc())
        )
    ).scalars().first()

    if rec is not None:
        actionable_guidance = ActionableGuidanceRead(
            urgency_level=rec.urgency_level,
            medical_alert=rec.medical_alert,
            primary_mode=rec.primary_mode,
            secondary_mode=rec.secondary_mode,
            target_goal=rec.target_goal,
            overall_interpretation=rec.overall_interpretation,
            home_trainings=rec.home_trainings or [],
        )
    elif metrics is not None:
        guidance_dict = (metrics.params or {}).get("actionable_guidance")
        if guidance_dict is not None:
            actionable_guidance = ActionableGuidanceRead.model_validate(guidance_dict)
        else:
            session = await _get_session(db, run.session_id)
            baseline_recall = (
                await _get_participant_baseline_recall(db, session.participant_id, session.id)
                if session is not None
                else None
            )
            iu_results = [
                {"code": iu.code, "suggested_status": sugg.suggested_status}
                for sugg, iu in suggestion_rows
            ]
            trend_deltas = None
            if baseline_recall is not None and iu_results:
                met_count = sum(1 for u in iu_results if u["suggested_status"] == "met")
                total_iu = len(iu_results)
                curr_recall = (met_count / total_iu * 100) if total_iu > 0 else None
                if curr_recall is not None:
                    trend_deltas = {"iu_recall_percent": round(curr_recall - baseline_recall, 2)}

            survivor_profile_dict = (
                await _get_survivor_profile_dict(db, session.caregiver_id)
                if session is not None
                else None
            )
            computed_guidance = ai_service.build_actionable_guidance(
                speech_metrics={
                    "speech_rate": float(metrics.speech_rate) if metrics.speech_rate is not None else None,
                    "articulation_rate": float(metrics.articulation_rate) if metrics.articulation_rate is not None else None,
                    "pause_rate_per_100_words": float(metrics.pause_rate_per_100_words) if metrics.pause_rate_per_100_words is not None else None,
                    "silent_pause_total_ms": metrics.silent_pause_total_ms,
                    "silent_pause_count": metrics.silent_pause_count,
                },
                iu_results=iu_results,
                trend_deltas=trend_deltas,
                survivor_profile=survivor_profile_dict,
            )
            actionable_guidance = ActionableGuidanceRead.model_validate(computed_guidance)
            if session is not None:
                new_rec = SessionTrainingRecommendation(
                    session_id=session.id,
                    run_id=run.id,
                    participant_id=session.participant_id,
                    urgency_level=computed_guidance.get("urgency_level", "routine"),
                    primary_mode=computed_guidance.get("primary_mode", "cst"),
                    secondary_mode=computed_guidance.get("secondary_mode"),
                    target_goal=computed_guidance.get("target_goal", ""),
                    overall_interpretation=computed_guidance.get("overall_interpretation", ""),
                    medical_alert=computed_guidance.get("medical_alert"),
                    home_trainings=computed_guidance.get("home_trainings", []),
                )
                db.add(new_rec)
                params = dict(metrics.params or {})
                params["actionable_guidance"] = computed_guidance
                metrics.params = params
                await db.commit()

    training_log_rows = list(
        (
            await db.execute(
                select(SessionTrainingLog)
                .where(SessionTrainingLog.session_id == run.session_id)
                .order_by(SessionTrainingLog.logged_at.desc(), SessionTrainingLog.id.desc())
            )
        )
        .scalars()
        .all()
    )
    training_logs = [TrainingLogRead.model_validate(row) for row in training_log_rows]

    return AnalysisRead(
        run_id=run.id,
        session_id=run.session_id,
        status=run.status,
        error_code=run.error_code,
        error_message=run.error_message,
        transcript_id=transcript.id if transcript is not None else None,
        transcript_source=transcript.source if transcript is not None else None,
        speech_metrics=speech,
        iu_suggestions=[
            IuSuggestionRead(
                iu_id=suggestion.iu_id,
                code=iu.code,
                description=iu.description,
                suggested_status=suggestion.suggested_status,
                evidence_quote=suggestion.evidence_quote,
                rationale=suggestion.rationale,
            )
            for suggestion, iu in suggestion_rows
        ],
        actionable_guidance=actionable_guidance,
        training_logs=training_logs,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.post(
    "/sessions/{session_id}/analysis",
    response_model=AnalysisRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_analysis(
    session_id: int,
    background: BackgroundTasks,
    data: AnalysisRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> AnalysisRead:
    data = data or AnalysisRunIn()
    session = await _require_session(db, session_id, current_user)
    if session.status in (SESSION_COMPLETED, SESSION_CANCELLED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already finalized or cancelled")
    rec = await _get_recording(db, session_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Upload a recording first")
    try:
        path = resolve_path(rec.storage_key)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Recording storage error")
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file missing")
    running = (
        await db.execute(
            select(SessionAnalysisRun).where(
                SessionAnalysisRun.session_id == session.id, SessionAnalysisRun.status == "running"
            )
        )
    ).scalars().first()
    if running is not None:
        # A run stuck in "running" past any plausible duration lost its
        # worker (crash/restart mid-run): auto-fail it so the session stays
        # analyzable instead of 409-ing forever.
        started = running.started_at or running.created_at
        stale_after = (
            settings.ASR_TIMEOUT_SECONDS + settings.AI_TIMEOUT_SECONDS + settings.FFMPEG_TIMEOUT_SECONDS + 300
        )
        if (_now() - started).total_seconds() > stale_after:
            running.status = "failed"
            running.error_code = "RUN_INTERRUPTED"
            running.error_message = "worker stopped before finishing (e.g. server restart)"
            running.finished_at = _now()
            await db.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Analysis already running for this session"
            )

    run = SessionAnalysisRun(
        session_id=session.id,
        status="running",
        started_at=_now(),
        created_by=current_user.id,
        requested_steps=data.model_dump(),
        asr_model=settings.ASR_MODEL,
        llm_model=settings.AI_MODEL or None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    background.add_task(_execute_run, run.id, session.id, data)
    return await _load_analysis_read(db, run)


@router.get("/sessions/{session_id}/analysis", response_model=AnalysisRead)
async def get_analysis(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> AnalysisRead:
    session = await _require_session(db, session_id, current_user)
    run = (
        await db.execute(
            select(SessionAnalysisRun)
            .where(SessionAnalysisRun.session_id == session.id)
            .order_by(SessionAnalysisRun.created_at.desc(), SessionAnalysisRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No analysis for this session")
    return await _load_analysis_read(db, run)


@router.post(
    "/sessions/{session_id}/training-logs",
    response_model=TrainingLogRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_training_log(
    session_id: int,
    data: TrainingLogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> TrainingLogRead:
    session = await _require_session(db, session_id, current_user)
    _check_session_access(session, current_user)

    log = SessionTrainingLog(
        session_id=session.id,
        participant_id=session.participant_id,
        caregiver_id=current_user.id,
        training_mode=data.training_mode.strip().lower(),
        title=data.title.strip(),
        status=data.status.strip().lower(),
        duration_minutes=data.duration_minutes,
        notes=data.notes.strip() if data.notes else None,
        logged_at=_now(),
    )
    db.add(log)
    await db.flush()

    db.add(
        AuditLog(
            actor_user_id=current_user.id,
            action="session.training_log.create",
            entity_type="session",
            entity_id=str(session.id),
            meta={"log_id": log.id, "training_mode": log.training_mode, "status": log.status},
        )
    )
    await db.commit()
    await db.refresh(log)
    return TrainingLogRead.model_validate(log)


@router.get(
    "/sessions/{session_id}/training-logs",
    response_model=list[TrainingLogRead],
)
async def get_training_logs(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> list[TrainingLogRead]:
    session = await _require_session(db, session_id, current_user)
    _check_session_access(session, current_user)

    logs = list(
        (
            await db.execute(
                select(SessionTrainingLog)
                .where(SessionTrainingLog.session_id == session.id)
                .order_by(SessionTrainingLog.logged_at.desc(), SessionTrainingLog.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [TrainingLogRead.model_validate(log) for log in logs]


@router.get(
    "/sessions/{session_id}/recommendation",
    response_model=SessionTrainingRecommendationRead,
)
async def get_session_recommendation(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> SessionTrainingRecommendation:
    session = await _require_session(db, session_id, current_user)
    _check_session_access(session, current_user)

    rec = (
        await db.execute(
            select(SessionTrainingRecommendation)
            .where(SessionTrainingRecommendation.session_id == session.id)
            .order_by(SessionTrainingRecommendation.id.desc())
        )
    ).scalars().first()

    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No training recommendation found for this session",
        )
    return rec


@router.get(
    "/sessions/{session_id}/recommendations",
    response_model=list[SessionTrainingRecommendationRead],
)
async def list_session_recommendations(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> list[SessionTrainingRecommendation]:
    session = await _require_session(db, session_id, current_user)
    _check_session_access(session, current_user)

    recs = list(
        (
            await db.execute(
                select(SessionTrainingRecommendation)
                .where(SessionTrainingRecommendation.session_id == session.id)
                .order_by(SessionTrainingRecommendation.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return recs

