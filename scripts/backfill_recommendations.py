"""Backfill script to populate session_training_recommendations for historical completed analysis runs."""

import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import (
    Session,
    SessionAnalysisRun,
    SessionAssessment,
    SessionIuSuggestion,
    SessionSpeechMetrics,
    SessionTrainingRecommendation,
    StoryInformationUnit,
)
from app.services import ai as ai_service
from app.services.scoring import SESSION_COMPLETED

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # Get all completed runs
        runs = list(
            (
                await db.execute(
                    select(SessionAnalysisRun)
                    .where(SessionAnalysisRun.status == "completed")
                    .order_by(SessionAnalysisRun.id.asc())
                )
            )
            .scalars()
            .all()
        )
        logger.info("Found %d completed runs.", len(runs))

        created_count = 0
        for run in runs:
            # Check if recommendation already exists
            existing = (
                await db.execute(
                    select(SessionTrainingRecommendation).where(
                        SessionTrainingRecommendation.run_id == run.id
                    )
                )
            ).scalars().first()
            if existing:
                logger.info("Run %d already has recommendation %d, skipping.", run.id, existing.id)
                continue

            session = (
                await db.execute(select(Session).where(Session.id == run.session_id))
            ).scalar_one_or_none()
            if not session:
                logger.warning("Run %d has no session %d, skipping.", run.id, run.session_id)
                continue

            metrics = (
                await db.execute(
                    select(SessionSpeechMetrics).where(SessionSpeechMetrics.run_id == run.id)
                )
            ).scalars().first()
            if not metrics:
                logger.warning("Run %d has no speech metrics, skipping.", run.id)
                continue

            # Load suggestions
            suggestions = (
                await db.execute(
                    select(SessionIuSuggestion, StoryInformationUnit)
                    .join(StoryInformationUnit, StoryInformationUnit.id == SessionIuSuggestion.iu_id)
                    .where(SessionIuSuggestion.run_id == run.id)
                )
            ).all()
            iu_results = [
                {"code": iu.code, "suggested_status": sugg.suggested_status}
                for sugg, iu in suggestions
            ]

            # Compute baseline recall if available
            baseline_row = (
                await db.execute(
                    select(SessionAssessment)
                    .join(Session, Session.id == SessionAssessment.session_id)
                    .where(
                        Session.participant_id == session.participant_id,
                        Session.status == SESSION_COMPLETED,
                        Session.id < session.id,
                    )
                    .order_by(Session.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            baseline_recall = float(baseline_row.iu_recall_percent) if baseline_row and baseline_row.iu_recall_percent is not None else None

            trend_deltas = None
            if baseline_recall is not None and iu_results:
                met_count = sum(1 for u in iu_results if u["suggested_status"] == "met")
                total_iu = len(iu_results)
                curr_recall = (met_count / total_iu * 100) if total_iu > 0 else None
                if curr_recall is not None:
                    trend_deltas = {"iu_recall_percent": round(curr_recall - baseline_recall, 2)}

            # Build guidance
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
            )

            # Persist recommendation
            rec = SessionTrainingRecommendation(
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
            db.add(rec)

            # Also update metrics.params cache
            params = dict(metrics.params or {})
            params["actionable_guidance"] = guidance
            metrics.params = params

            created_count += 1
            logger.info(
                "Created recommendation for run %d (session %d, participant %d): mode=%s, urgency=%s",
                run.id, session.id, session.participant_id, rec.primary_mode, rec.urgency_level
            )

        await db.commit()
        logger.info("Successfully backfilled %d recommendations.", created_count)


if __name__ == "__main__":
    asyncio.run(main())
