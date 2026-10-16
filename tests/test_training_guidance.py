from app.schemas.training import ActionableGuidanceRead, TrainingLogCreate
from app.services.ai import build_actionable_guidance


def test_guidance_sfa_triggered_by_word_finding_gap() -> None:
    # High articulation rate but low speech rate due to pause searching
    metrics = {
        "articulation_rate": 168.18,
        "speech_rate": 94.39,
        "pause_rate_per_100_words": 65.0,
        "silent_pause_total_ms": 15000,
        "silent_pause_count": 25,
    }
    ius = [
        {"code": "IU1", "suggested_status": "met"},
        {"code": "IU2", "suggested_status": "met"},
        {"code": "IU3", "suggested_status": "met"},
        {"code": "IU4", "suggested_status": "met"},
    ]
    result = build_actionable_guidance(metrics, ius)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.primary_mode == "sfa"
    assert any(e.training_mode == "sfa" and e.level == 1 for e in guidance.home_trainings)
    assert "SFA" in guidance.target_goal or "mencari kata" in guidance.target_goal.lower()


def test_guidance_srt_triggered_by_missed_detail() -> None:
    # Good articulation and speech rate, but missed specific numeric/detail IU
    metrics = {
        "articulation_rate": 140.0,
        "speech_rate": 120.0,
        "pause_rate_per_100_words": 20.0,
    }
    ius = [
        {"code": "IU1", "suggested_status": "not_met"},  # Missed detail (IU1)
        {"code": "IU2", "suggested_status": "met"},
        {"code": "IU3", "suggested_status": "met"},
        {"code": "IU4", "suggested_status": "met"},
    ]
    result = build_actionable_guidance(metrics, ius)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.primary_mode == "srt"
    assert any(e.training_mode == "srt" and e.level == 2 for e in guidance.home_trainings)
    assert "detail" in guidance.target_goal.lower()


def test_guidance_cst_triggered_by_low_recall() -> None:
    # Low recall overall (<50%)
    metrics = {
        "articulation_rate": 110.0,
        "speech_rate": 80.0,
        "pause_rate_per_100_words": 30.0,
    }
    ius = [
        {"code": "IU2", "suggested_status": "met"},
        {"code": "IU3", "suggested_status": "not_met"},
        {"code": "IU4", "suggested_status": "not_met"},
        {"code": "IU7", "suggested_status": "not_met"},
    ]
    result = build_actionable_guidance(metrics, ius)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.primary_mode == "cst"
    assert any(e.training_mode == "cst" and e.level == 3 for e in guidance.home_trainings)


def test_guidance_medical_alert_on_significant_drop() -> None:
    metrics = {
        "articulation_rate": 140.0,
        "speech_rate": 110.0,
    }
    ius = [
        {"code": "IU1", "suggested_status": "met"},
        {"code": "IU2", "suggested_status": "met"},
    ]
    # Dropped 25% from baseline session
    trend_deltas = {"iu_recall_percent": -25.0}

    result = build_actionable_guidance(metrics, ius, trend_deltas=trend_deltas)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.urgency_level == "medical_consultation_advised"
    assert guidance.medical_alert is not None
    assert "Peringatan Medis" in guidance.medical_alert
    assert "Neurolog" in guidance.medical_alert


def test_guidance_needs_monitoring_low_recall() -> None:
    metrics = {
        "articulation_rate": 130.0,
        "speech_rate": 100.0,
    }
    # 1 of 4 met = 25% recall (< 40%)
    ius = [
        {"code": "IU1", "suggested_status": "met"},
        {"code": "IU2", "suggested_status": "not_met"},
        {"code": "IU3", "suggested_status": "not_met"},
        {"code": "IU4", "suggested_status": "not_met"},
    ]
    result = build_actionable_guidance(metrics, ius)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.urgency_level == "needs_monitoring"
    assert guidance.medical_alert is not None
    assert "40%" in guidance.medical_alert


def test_training_log_create_schema() -> None:
    valid = TrainingLogCreate(
        training_mode="sfa",
        title="Tebak Ciri Objek Sekitar",
        status="completed",
        duration_minutes=15,
        notes="Peserta sangat bersemangat menyebutkan ciri-ciri apel dan sendok.",
    )
    assert valid.training_mode == "sfa"
    assert valid.duration_minutes == 15


def test_build_progression_note() -> None:
    from app.api.v1.routes.participants import _build_progression_note
    from app.schemas.analysis import TrendDelta, TrendPoint

    baseline = TrendPoint(
        session_id=1,
        recommended_mode="sfa",
        trainings_completed_count=4,
    )
    latest = TrendPoint(session_id=2)
    deltas = TrendDelta(
        speech_rate=6.5,
        pause_rate_per_100_words=-5.2,
        iu_recall_percent=10.0,
    )

    note = _build_progression_note(baseline, latest, deltas)
    assert "Setelah 4x latihan (SFA)" in note
    assert "laju bicara meningkat" in note
    assert "jeda hening berkurang" in note
    assert "daya ingat recall meningkat" in note


def test_session_training_recommendation_schema() -> None:
    from datetime import datetime, timezone
    from app.schemas.training import SessionTrainingRecommendationRead

    rec_data = {
        "id": 1,
        "session_id": 10,
        "run_id": 42,
        "participant_id": 3,
        "urgency_level": "routine",
        "primary_mode": "sfa",
        "secondary_mode": "srt",
        "target_goal": "Mengurangi jeda hening",
        "overall_interpretation": "Bicara stabil dengan jeda kata.",
        "medical_alert": None,
        "home_trainings": [
            {
                "training_mode": "sfa",
                "level": 1,
                "level_title": "Level 1 - Objek",
                "title": "Tebak Ciri Objek",
                "target_area": "Pencarian Kosakata",
                "instructions": "Sebutkan ciri objek.",
                "frequency": "1x sehari",
                "duration_minutes": 5,
                "method_basis": "SFA",
            }
        ],
        "created_at": datetime.now(timezone.utc),
    }

    read = SessionTrainingRecommendationRead.model_validate(rec_data)
    assert read.id == 1
    assert read.primary_mode == "sfa"
    assert len(read.home_trainings) == 1
    assert read.home_trainings[0].level == 1


def test_build_caregiver_report_baseline() -> None:
    from app.api.v1.routes.participants import _build_caregiver_report
    from app.schemas.analysis import TrendPoint

    pt = TrendPoint(
        session_id=1,
        session_number=1,
        session_label="Sesi 1 (Baseline)",
        iu_recall_percent=55.0,
        speech_rate=120.0,
        pause_rate_per_100_words=45.0,
        recommended_mode="sfa",
        training_target_goal="Mengurangi durasi hening",
    )
    report = _build_caregiver_report(
        participant_name="Budi",
        series=[pt],
        baseline=pt,
        latest=pt,
        deltas=None,
        latest_rec=None,
        total_trainings=0,
    )
    assert report.status_badge == "Asesmen Awal"
    assert "Budi" in report.headline
    assert "SFA" in report.treatment_progress
    assert len(report.key_findings) >= 2


def test_build_caregiver_report_multisession() -> None:
    from app.api.v1.routes.participants import _build_caregiver_report
    from app.schemas.analysis import TrendDelta, TrendPoint

    base = TrendPoint(
        session_id=1,
        session_number=1,
        session_label="Sesi 1 (Baseline)",
        iu_recall_percent=40.0,
        speech_rate=100.0,
        pause_rate_per_100_words=60.0,
        recommended_mode="sfa",
    )
    latest = TrendPoint(
        session_id=2,
        session_number=2,
        session_label="Sesi 2",
        iu_recall_percent=65.0,
        speech_rate=125.0,
        pause_rate_per_100_words=35.0,
        recommended_mode="sfa",
        training_target_goal="Pertahankan kelancaran",
    )
    deltas = TrendDelta(
        iu_recall_percent=25.0,
        speech_rate=25.0,
        pause_rate_per_100_words=-25.0,
    )
    report = _build_caregiver_report(
        participant_name="Siti",
        series=[base, latest],
        baseline=base,
        latest=latest,
        deltas=deltas,
        latest_rec=None,
        total_trainings=4,
    )
    assert report.status_badge == "Kemajuan Positif"
    assert "Siti" in report.headline
    assert "4 kali latihan" in report.treatment_progress
    assert "+25.0%" in report.assessment_summary



def test_guidance_personalization_with_survivor_profile_food_and_javanese() -> None:
    metrics = {
        "articulation_rate": 180.0,
        "speech_rate": 120.0,
        "pause_rate_per_100_words": 65.0,
        "silent_pause_total_ms": 3000,
        "silent_pause_count": 5,
    }
    ius = [{"code": "IU1", "status": "met"}, {"code": "IU2", "status": "met"}]
    profile = {
        "name": "Bu Siti",
        "primary_language": "jv",
        "preferred_topics": ["food"],
        "preferred_session_duration": "5",
        "instruction_preference": "short_simple",
    }
    result = build_actionable_guidance(metrics, ius, survivor_profile=profile)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.primary_mode == "sfa"
    assert "Bu Siti" in guidance.overall_interpretation
    # Check that SFA instructions are customized for food and Bu Siti
    sfa_item = next(e for e in guidance.home_trainings if e.training_mode == "sfa")
    assert "bahan makanan atau alat dapur" in sfa_item.instructions
    assert "Bu Siti" in sfa_item.instructions
    assert "secara singkat" in sfa_item.instructions
    assert sfa_item.duration_minutes == 5
    # Check Javanese daily tip
    assert any("Bahasa Jawa" in tip for tip in guidance.caregiver_daily_tips)


def test_guidance_personalization_with_survivor_profile_family_and_sundanese() -> None:
    metrics = {
        "articulation_rate": 110.0,
        "speech_rate": 80.0,
        "pause_rate_per_100_words": 30.0,
        "silent_pause_total_ms": 2000,
        "silent_pause_count": 2,
    }
    ius = [
        {"code": "IU2", "status": "met"},
        {"code": "IU3", "status": "not_met"},
        {"code": "IU4", "status": "not_met"},
        {"code": "IU7", "status": "not_met"},
    ]
    profile = {
        "name": "Pak Budi",
        "primary_language": "su",
        "preferred_topics": ["family"],
        "preferred_session_duration": "3",
        "instruction_preference": "companion_assistance",
    }
    result = build_actionable_guidance(metrics, ius, survivor_profile=profile)
    guidance = ActionableGuidanceRead.model_validate(result)

    assert guidance.primary_mode == "cst"
    assert "Pak Budi" in guidance.overall_interpretation
    cst_item = next(e for e in guidance.home_trainings if e.training_mode == "cst")
    assert "Pak Budi" in cst_item.instructions
    assert "keluarga" in cst_item.instructions
    assert cst_item.duration_minutes == 3
    assert any("Bahasa Sunda" in tip for tip in guidance.caregiver_daily_tips)


