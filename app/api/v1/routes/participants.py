from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_admin
from app.core.database import get_db
from app.models import (
    Participant,
    Session,
    SessionAnalysisRun,
    SessionAssessment,
    SessionSpeechMetrics,
    Users,
)
from app.schemas.analysis import ParticipantTrendRead, TrendDelta, TrendPoint
from app.schemas.participant import ParticipantCreate, ParticipantRead
from app.services.scoring import SESSION_COMPLETED

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


def _delta(latest: float | None, baseline: float | None) -> float | None:
    if latest is None or baseline is None:
        return None
    return round(latest - baseline, 2)


@router.get("/{participant_id}/analysis-trend", response_model=ParticipantTrendRead)
async def get_participant_analysis_trend(
    participant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> ParticipantTrendRead:
    p = (await db.execute(select(Participant).where(Participant.id == participant_id))).scalar_one_or_none()
    if p is None or p.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    if not is_admin(current_user) and p.created_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this participant")

    sessions = list(
        (
            await db.execute(
                select(Session)
                .where(Session.participant_id == p.id, Session.status == SESSION_COMPLETED)
                .order_by(Session.completed_at.asc(), Session.id.asc())
            )
        )
        .scalars()
        .all()
    )

    series: list[TrendPoint] = []
    for s in sessions:
        assessment = (
            await db.execute(
                select(SessionAssessment).where(
                    SessionAssessment.session_id == s.id, SessionAssessment.status == "final"
                )
            )
        ).scalar_one_or_none()
        # Metrics of the session's latest completed analysis run (None when the
        # session was finalized without an analysis).
        metrics = (
            await db.execute(
                select(SessionSpeechMetrics)
                .join(SessionAnalysisRun, SessionAnalysisRun.id == SessionSpeechMetrics.run_id)
                .where(
                    SessionSpeechMetrics.session_id == s.id,
                    SessionAnalysisRun.status == "completed",
                )
                .order_by(SessionAnalysisRun.created_at.desc(), SessionAnalysisRun.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        series.append(
            TrendPoint(
                session_id=s.id,
                completed_at=s.completed_at,
                iu_recall_percent=(
                    float(assessment.iu_recall_percent)
                    if assessment is not None and assessment.iu_recall_percent is not None
                    else None
                ),
                speech_rate=float(metrics.speech_rate) if metrics and metrics.speech_rate is not None else None,
                articulation_rate=(
                    float(metrics.articulation_rate) if metrics and metrics.articulation_rate is not None else None
                ),
                pause_rate_per_100_words=(
                    float(metrics.pause_rate_per_100_words)
                    if metrics and metrics.pause_rate_per_100_words is not None
                    else None
                ),
                silent_pause_total_ms=metrics.silent_pause_total_ms if metrics else None,
                silent_pause_count=metrics.silent_pause_count if metrics else None,
                syllable_count=metrics.syllable_count if metrics else None,
                word_count=metrics.word_count if metrics else None,
            )
        )

    if len(series) < 2:
        return ParticipantTrendRead(
            participant_id=p.id,
            display_name=p.display_name,
            session_count=len(series),
            series=series,
            baseline=series[0] if series else None,
            latest=series[-1] if series else None,
            deltas=None,
        )

    baseline, latest = series[0], series[-1]
    return ParticipantTrendRead(
        participant_id=p.id,
        display_name=p.display_name,
        session_count=len(series),
        series=series,
        baseline=baseline,
        latest=latest,
        deltas=TrendDelta(
            iu_recall_percent=_delta(latest.iu_recall_percent, baseline.iu_recall_percent),
            speech_rate=_delta(latest.speech_rate, baseline.speech_rate),
            articulation_rate=_delta(latest.articulation_rate, baseline.articulation_rate),
            pause_rate_per_100_words=_delta(latest.pause_rate_per_100_words, baseline.pause_rate_per_100_words),
            silent_pause_total_ms=_delta(
                float(latest.silent_pause_total_ms) if latest.silent_pause_total_ms is not None else None,
                float(baseline.silent_pause_total_ms) if baseline.silent_pause_total_ms is not None else None,
            ),
        ),
    )
