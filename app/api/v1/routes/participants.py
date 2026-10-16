from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_admin
from app.core.database import get_db
from app.models import (
    Participant,
    Session,
    SessionAnalysisRun,
    SessionAssessment,
    SessionSpeechMetrics,
    SessionTrainingLog,
    SessionTrainingRecommendation,
    SurvivorProfiles,
    Users,
)
from app.schemas.analysis import (
    CaregiverReportRead,
    ParticipantTrendRead,
    TrendDelta,
    TrendPoint,
)
from app.schemas.participant import ParticipantCreate, ParticipantRead
from app.schemas.training import SessionTrainingRecommendationRead
from app.services import ai as ai_service
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


MODE_NAMES = {
    "sfa": "Stimulasi Penamaan Objek (Semantic Feature Analysis - SFA)",
    "srt": "Retensi Detail Bertahap (Spaced Retrieval Training - SRT)",
    "cst": "Stimulasi Kognitif Naratif (Cognitive Stimulation Therapy - CST)",
}


def _build_progression_note(
    baseline: TrendPoint,
    latest: TrendPoint,
    deltas: TrendDelta,
    total_trainings: int | None = None,
) -> str:
    notes: list[str] = []
    if deltas.iu_recall_percent is not None:
        if deltas.iu_recall_percent <= -20.0:
            return (
                f"Peringatan Medis: Terdeteksi penurunan daya ingat recall cerita sebesar {abs(deltas.iu_recall_percent):.1f}% "
                "dibanding baseline. Disarankan segera berkonsultasi dengan Dokter Spesialis Saraf."
            )
        elif deltas.iu_recall_percent > 0:
            notes.append(f"daya ingat recall meningkat (+{deltas.iu_recall_percent:.1f}%)")
        elif deltas.iu_recall_percent < 0:
            notes.append(f"daya ingat recall sedikit menurun ({deltas.iu_recall_percent:.1f}%)")

    if deltas.pause_rate_per_100_words is not None and deltas.pause_rate_per_100_words < 0:
        notes.append(f"frekuensi jeda hening berkurang ({abs(deltas.pause_rate_per_100_words):.1f}/100 kata)")

    if deltas.speech_rate is not None and deltas.speech_rate > 0:
        notes.append(f"laju bicara meningkat (+{deltas.speech_rate:.1f} suku kata/menit)")

    prefix = ""
    trainings_count = total_trainings if total_trainings is not None else baseline.trainings_completed_count
    if trainings_count > 0:
        mode_str = f" ({baseline.recommended_mode.upper()})" if baseline.recommended_mode else ""
        prefix = f"Setelah {trainings_count}x latihan{mode_str}: "
    else:
        prefix = "Evaluasi berkala: "

    if notes:
        return prefix + ", ".join(notes) + "."
    return prefix + "performa bicara dan memori peserta stabil dibanding sesi baseline."


def _build_caregiver_report(
    participant_name: str,
    series: list[TrendPoint],
    baseline: TrendPoint,
    latest: TrendPoint,
    deltas: TrendDelta | None,
    latest_rec: SessionTrainingRecommendation | None,
    total_trainings: int,
) -> CaregiverReportRead:
    mode_key = (latest.recommended_mode or "sfa").lower()
    mode_full_name = MODE_NAMES.get(mode_key, mode_key.upper())
    target_goal = latest.training_target_goal or (
        latest_rec.target_goal if latest_rec else "Meningkatkan kemampuan komunikasi fungsional."
    )

    # 1. Baseline only
    if len(series) <= 1 or deltas is None:
        key_findings = [
            (
                f"Daya ingat recall cerita awal: {latest.iu_recall_percent:.1f}%"
                if latest.iu_recall_percent is not None
                else "Hasil asesmen daya ingat tercatat."
            ),
            (
                f"Laju bicara: {latest.speech_rate:.1f} suku kata/menit"
                if latest.speech_rate is not None
                else "Laju bicara awal tercatat."
            ),
            f"Program latihan yang disarankan: {mode_full_name}",
        ]
        return CaregiverReportRead(
            headline=f"Hasil Asesmen Awal (Baseline) {participant_name}",
            status_badge="Asesmen Awal",
            assessment_summary=(
                f"Pemeriksaan awal untuk {participant_name} telah selesai direkam. "
                + (
                    f"Daya ingat terhadap detail cerita berada di angka {latest.iu_recall_percent:.1f}%. "
                    if latest.iu_recall_percent is not None
                    else ""
                )
                + "Hasil ini menjadi acuan dasar (baseline) untuk membandingkan perkembangan memori dan kelancaran bicara pada evaluasi berikutnya."
            ),
            treatment_progress=(
                f"Sebagai langkah awal, disarankan memulai program latihan mandiri di rumah menggunakan metode {mode_full_name}. "
                f"Tujuan utama latihan: '{target_goal}'."
            ),
            key_findings=key_findings,
            caregiver_action_plan=(
                "Dampingi peserta melakukan latihan stimulasi kognitif di rumah 1-2 kali sehari selama 5-10 menit dalam suasana yang tenang dan santai. "
                "Berikan waktu yang cukup saat peserta mencari kata dan catat setiap kali selesai latihan pada aplikasi."
            ),
            medical_alert=latest_rec.medical_alert if latest_rec else None,
        )

    # 2. Multi-session progression
    delta_recall = deltas.iu_recall_percent
    delta_speech = deltas.speech_rate
    delta_pause = deltas.pause_rate_per_100_words

    medical_alert = latest_rec.medical_alert if latest_rec else None
    if delta_recall is not None and delta_recall <= -20.0:
        status_badge = "Konsultasi Medis Disarankan"
        headline = f"Peringatan Evaluasi: Terdeteksi Penurunan Daya Ingat pada {participant_name}"
        if not medical_alert:
            medical_alert = (
                f"Peringatan Medis: Terdeteksi penurunan daya ingat recall cerita sebesar {abs(delta_recall):.1f}% "
                "dibanding baseline. Disarankan segera berkonsultasi dengan Dokter Spesialis Saraf (Neurolog)."
            )
    elif (delta_recall is not None and delta_recall >= 10.0) or (
        delta_speech is not None and delta_speech >= 10.0 and delta_pause is not None and delta_pause < 0
    ):
        status_badge = "Kemajuan Positif"
        headline = f"Perkembangan Positif: Kemampuan Daya Ingat dan Bicara {participant_name} Meningkat"
    elif (delta_recall is not None and delta_recall < -5.0) or (
        latest.iu_recall_percent is not None and latest.iu_recall_percent < 40.0
    ):
        status_badge = "Perlu Pendampingan Khusus"
        headline = f"Evaluasi Berkala: {participant_name} Memerlukan Dukungan Latihan Lebih Intensif"
        if not medical_alert and latest.iu_recall_percent is not None and latest.iu_recall_percent < 40.0:
            medical_alert = (
                "Catatan Klinis: Skor daya ingat berada di bawah 40%. "
                "Disarankan untuk terus mendampingi latihan secara rutin dan memantau kemajuan."
            )
    else:
        status_badge = "Performa Stabil"
        headline = f"Performa Stabil: Hasil Evaluasi Berkala {participant_name}"

    parts: list[str] = []
    if delta_recall is not None and baseline.iu_recall_percent is not None and latest.iu_recall_percent is not None:
        sign = "+" if delta_recall > 0 else ""
        if delta_recall > 0:
            parts.append(
                f"Kemampuan daya ingat recall cerita mengalami kemajuan positif, meningkat dari {baseline.iu_recall_percent:.1f}% "
                f"(sesi baseline) menjadi {latest.iu_recall_percent:.1f}% pada evaluasi terbaru ({sign}{delta_recall:.1f}%)."
            )
        elif delta_recall < 0:
            parts.append(
                f"Daya ingat recall cerita mengalami penurunan dari {baseline.iu_recall_percent:.1f}% "
                f"(sesi baseline) menjadi {latest.iu_recall_percent:.1f}% ({delta_recall:.1f}%)."
            )
        else:
            parts.append(f"Daya ingat recall cerita relatif stabil di angka {latest.iu_recall_percent:.1f}%.")

    if delta_pause is not None and delta_speech is not None:
        if delta_pause < 0 and delta_speech > 0:
            parts.append(
                f"Kelancaran bicara menunjukkan perbaikan nyata dengan berkurangnya frekuensi jeda hening "
                f"({abs(delta_pause):.1f} jeda lebih sedikit per 100 kata) dan kenaikan laju bicara (+{delta_speech:.1f} suku kata/menit)."
            )
        elif delta_pause > 0 and latest.pause_rate_per_100_words is not None:
            parts.append(
                f"Peserta masih memerlukan waktu jeda berpikir yang cukup sering saat mencari kata "
                f"({latest.pause_rate_per_100_words:.1f} jeda per 100 kata)."
            )
        else:
            parts.append("Pola jeda dan tempo bicara peserta terpantau stabil dibanding sesi baseline.")
    assessment_summary = " ".join(parts) if parts else f"Evaluasi berkala menunjukkan kondisi performa bicara dan memori {participant_name} stabil."

    if total_trainings > 0:
        treatment_progress = (
            f"Keluarga/caregiver telah menyelesaikan dan mencatat sebanyak {total_trainings} kali latihan mandiri di rumah. "
            f"Kepatuhan latihan ini sangat membantu dalam mempertahankan kemampuan kognitif dan komunikasi peserta. "
            f"Fokus intervensi aktif saat ini adalah {mode_full_name} dengan target: '{target_goal}'."
        )
    else:
        treatment_progress = (
            f"Belum ada sesi latihan mandiri yang dicatat di sistem untuk periode ini. "
            f"Sangat dianjurkan untuk mulai mendampingi dan mencatat latihan mandiri di rumah menggunakan metode {mode_full_name} "
            f"guna membantu mencapai target: '{target_goal}'."
        )

    key_findings = []
    if delta_recall is not None and latest.iu_recall_percent is not None:
        sign = "+" if delta_recall > 0 else ""
        key_findings.append(f"Daya ingat recall cerita: {latest.iu_recall_percent:.1f}% ({sign}{delta_recall:.1f}% dibanding baseline)")
    if latest.pause_rate_per_100_words is not None:
        sign = ("+" if delta_pause > 0 else "") if delta_pause is not None else ""
        diff_str = f" ({sign}{delta_pause:.1f}/100 kata)" if delta_pause is not None else ""
        key_findings.append(f"Frekuensi jeda mencari kata: {latest.pause_rate_per_100_words:.1f}/100 kata{diff_str}")
    key_findings.append(f"Total latihan mandiri diselesaikan: {total_trainings} sesi latihan")
    key_findings.append(f"Fokus terapi aktif: {mode_full_name}")

    if mode_key == "sfa":
        caregiver_action_plan = (
            "Lakukan latihan 'Tebak Ciri Objek' 1-2 kali sehari (durasi 5-10 menit). "
            "Ajak peserta menyebutkan fungsi, warna, atau kegunaan benda sebelum menyebutkan namanya. "
            "Beri waktu jeda minimal 5 detik dan jangan langsung memotong atau mengoreksi saat peserta sedang mencari kata."
        )
    elif mode_key == "srt":
        caregiver_action_plan = (
            "Lakukan latihan 'Mengingat Detail Bertahap' (Spaced Retrieval) 1 kali sehari (durasi 10 menit). "
            "Sebutkan 2-3 fakta spesifik (angka atau nama tempat) lalu minta peserta mengingatnya kembali setelah jeda 30 detik, 2 menit, lalu 5 menit secara rileks."
        )
    else:
        caregiver_action_plan = (
            "Ajak peserta berdiskusi santai mengenai topik harian atau menceritakan kembali kegiatan hari ini "
            "untuk merangsang alur kalimat naratif yang runtut dan mempertahankan tempo bicara yang nyaman."
        )

    return CaregiverReportRead(
        headline=headline,
        status_badge=status_badge,
        assessment_summary=assessment_summary,
        treatment_progress=treatment_progress,
        key_findings=key_findings,
        caregiver_action_plan=caregiver_action_plan,
        medical_alert=medical_alert,
    )



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

    profile = (
        await db.execute(select(SurvivorProfiles).where(SurvivorProfiles.user_id == p.created_by))
    ).scalar_one_or_none()
    survivor_profile_dict = (
        {
            "name": profile.name,
            "primary_language": profile.primary_language,
            "preferred_topics": profile.preferred_topics or [],
            "instruction_preference": profile.instruction_preference,
            "preferred_session_duration": profile.preferred_session_duration,
            "practice_mode": profile.practice_mode,
        }
        if profile is not None
        else None
    )

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

    total_trainings_completed = (
        await db.execute(
            select(func.count(SessionTrainingLog.id)).where(
                SessionTrainingLog.participant_id == p.id,
                SessionTrainingLog.status == "completed",
            )
        )
    ).scalar_one() or 0

    series: list[TrendPoint] = []
    for idx, s in enumerate(sessions):
        session_number = idx + 1
        session_label = "Sesi 1 (Baseline)" if idx == 0 else f"Sesi {session_number}"

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

        completed_trainings = (
            await db.execute(
                select(func.count(SessionTrainingLog.id)).where(
                    SessionTrainingLog.session_id == s.id,
                    SessionTrainingLog.status == "completed",
                )
            )
        ).scalar_one() or 0

        rec = (
            await db.execute(
                select(SessionTrainingRecommendation)
                .where(SessionTrainingRecommendation.session_id == s.id)
                .order_by(SessionTrainingRecommendation.id.desc())
            )
        ).scalars().first()

        recommended_mode = rec.primary_mode if rec else None
        training_target_goal = rec.target_goal if rec else None
        urgency_level = rec.urgency_level if rec else None
        clinical_interpretation = rec.overall_interpretation if rec else None

        if rec is None:
            guidance = (metrics.params or {}).get("actionable_guidance") if metrics and metrics.params else None
            if guidance is None and metrics is not None:
                guidance = ai_service.build_actionable_guidance(
                    speech_metrics={
                        "speech_rate": float(metrics.speech_rate) if metrics.speech_rate is not None else None,
                        "articulation_rate": float(metrics.articulation_rate) if metrics.articulation_rate is not None else None,
                        "pause_rate_per_100_words": float(metrics.pause_rate_per_100_words) if metrics.pause_rate_per_100_words is not None else None,
                        "silent_pause_total_ms": metrics.silent_pause_total_ms,
                        "silent_pause_count": metrics.silent_pause_count,
                    },
                    iu_results=None,
                    survivor_profile=survivor_profile_dict,
                )
            if guidance:
                recommended_mode = guidance.get("primary_mode")
                training_target_goal = guidance.get("target_goal")
                urgency_level = guidance.get("urgency_level")
                clinical_interpretation = guidance.get("overall_interpretation")

        series.append(
            TrendPoint(
                session_id=s.id,
                session_number=session_number,
                session_label=session_label,
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
                recommended_mode=recommended_mode,
                training_target_goal=training_target_goal,
                trainings_completed_count=completed_trainings,
                urgency_level=urgency_level,
                clinical_interpretation=clinical_interpretation,
            )
        )

    latest_rec = (
        await db.execute(
            select(SessionTrainingRecommendation)
            .where(SessionTrainingRecommendation.participant_id == p.id)
            .order_by(SessionTrainingRecommendation.id.desc())
        )
    ).scalars().first() if series else None

    if len(series) < 2:
        baseline = series[0] if series else None
        caregiver_report = (
            _build_caregiver_report(
                p.display_name,
                series,
                baseline,
                baseline,
                None,
                latest_rec,
                total_trainings_completed,
            )
            if baseline
            else None
        )
        return ParticipantTrendRead(
            participant_id=p.id,
            display_name=p.display_name,
            session_count=len(series),
            total_trainings_completed=total_trainings_completed,
            current_recommended_mode=series[0].recommended_mode if series else None,
            current_target_goal=series[0].training_target_goal if series else None,
            series=series,
            baseline=baseline,
            latest=baseline,
            deltas=None,
            progression_note=(
                "Sesi baseline awal tercatat. Lakukan latihan kognitif dan evaluasi ulang untuk melihat grafik perkembangan."
                if series
                else None
            ),
            caregiver_report=caregiver_report,
        )

    baseline, latest = series[0], series[-1]
    deltas = TrendDelta(
        iu_recall_percent=_delta(latest.iu_recall_percent, baseline.iu_recall_percent),
        speech_rate=_delta(latest.speech_rate, baseline.speech_rate),
        articulation_rate=_delta(latest.articulation_rate, baseline.articulation_rate),
        pause_rate_per_100_words=_delta(latest.pause_rate_per_100_words, baseline.pause_rate_per_100_words),
        silent_pause_total_ms=_delta(
            float(latest.silent_pause_total_ms) if latest.silent_pause_total_ms is not None else None,
            float(baseline.silent_pause_total_ms) if baseline.silent_pause_total_ms is not None else None,
        ),
    )
    progression_note = _build_progression_note(baseline, latest, deltas, total_trainings_completed)
    caregiver_report = _build_caregiver_report(
        p.display_name,
        series,
        baseline,
        latest,
        deltas,
        latest_rec,
        total_trainings_completed,
    )

    return ParticipantTrendRead(
        participant_id=p.id,
        display_name=p.display_name,
        session_count=len(series),
        total_trainings_completed=total_trainings_completed,
        current_recommended_mode=latest.recommended_mode,
        current_target_goal=latest.training_target_goal,
        series=series,
        baseline=baseline,
        latest=latest,
        deltas=deltas,
        progression_note=progression_note,
        caregiver_report=caregiver_report,
    )


@router.get(
    "/{participant_id}/recommendations",
    response_model=list[SessionTrainingRecommendationRead],
)
async def list_participant_recommendations(
    participant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> list[SessionTrainingRecommendation]:
    p = (await db.execute(select(Participant).where(Participant.id == participant_id))).scalar_one_or_none()
    if p is None or p.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    if not is_admin(current_user) and p.created_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this participant")

    recs = list(
        (
            await db.execute(
                select(SessionTrainingRecommendation)
                .where(SessionTrainingRecommendation.participant_id == p.id)
                .order_by(SessionTrainingRecommendation.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return recs

