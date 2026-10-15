from datetime import datetime

from pydantic import BaseModel

from app.schemas.training import ActionableGuidanceRead, TrainingLogRead


class AnalysisRunIn(BaseModel):
    run_transcription: bool = True
    run_speech_metrics: bool = True
    run_iu_suggestions: bool = True


class SilentPauseRead(BaseModel):
    ordinal: int
    start_ms: int
    end_ms: int
    duration_ms: int
    duration_log: float | None = None


class SpeechMetricsRead(BaseModel):
    run_id: int
    session_id: int
    analysis_method: str
    file_duration_ms: int
    lead_silence_ms: int
    tail_silence_ms: int
    speech_duration_ms: int
    phonation_ms: int
    silent_pause_total_ms: int
    silent_pause_count: int
    silent_pause_mean_ms: float | None = None
    silent_pause_median_ms: float | None = None
    silent_pause_sd_ms: float | None = None
    silent_pause_mean_log: float | None = None
    silent_pause_median_log: float | None = None
    silent_pause_sd_log: float | None = None
    silent_pause_total_log: float | None = None
    speech_rate: float | None = None
    articulation_rate: float | None = None
    speech_rate_wpm: float | None = None
    articulation_rate_wpm: float | None = None
    pause_rate_per_100_words: float | None = None
    syllable_count: int
    word_count: int
    filled_pause_count: int
    quality_flag: str | None = None
    silent_pauses: list[SilentPauseRead] = []
    silent_pause_durations_ms: list[int] = []
    created_at: datetime


class IuSuggestionRead(BaseModel):
    iu_id: int
    code: str
    description: str
    suggested_status: str
    evidence_quote: str | None = None
    rationale: str | None = None


class AnalysisRead(BaseModel):
    run_id: int
    session_id: int
    status: str
    error_code: str | None = None
    error_message: str | None = None
    transcript_id: int | None = None
    transcript_source: str | None = None
    speech_metrics: SpeechMetricsRead | None = None
    iu_suggestions: list[IuSuggestionRead] = []
    actionable_guidance: ActionableGuidanceRead | None = None
    training_logs: list[TrainingLogRead] = []
    started_at: datetime
    finished_at: datetime | None = None


class TrendPoint(BaseModel):
    session_id: int
    session_number: int | None = None
    session_label: str | None = None
    completed_at: datetime | None = None
    iu_recall_percent: float | None = None
    speech_rate: float | None = None
    articulation_rate: float | None = None
    pause_rate_per_100_words: float | None = None
    silent_pause_total_ms: int | None = None
    silent_pause_count: int | None = None
    syllable_count: int | None = None
    word_count: int | None = None
    recommended_mode: str | None = None
    training_target_goal: str | None = None
    trainings_completed_count: int = 0
    urgency_level: str | None = None
    clinical_interpretation: str | None = None


class TrendDelta(BaseModel):
    iu_recall_percent: float | None = None
    speech_rate: float | None = None
    articulation_rate: float | None = None
    pause_rate_per_100_words: float | None = None
    silent_pause_total_ms: float | None = None


class CaregiverReportRead(BaseModel):
    headline: str
    status_badge: str
    assessment_summary: str
    treatment_progress: str
    key_findings: list[str] = []
    caregiver_action_plan: str
    medical_alert: str | None = None


class ParticipantTrendRead(BaseModel):
    participant_id: int
    display_name: str
    session_count: int
    total_trainings_completed: int = 0
    current_recommended_mode: str | None = None
    current_target_goal: str | None = None
    series: list[TrendPoint] = []
    baseline: TrendPoint | None = None
    latest: TrendPoint | None = None
    deltas: TrendDelta | None = None
    progression_note: str | None = None
    caregiver_report: CaregiverReportRead | None = None

