from datetime import datetime

from pydantic import BaseModel


class AnalysisRunIn(BaseModel):
    run_transcription: bool = True
    run_speech_metrics: bool = True
    run_iu_suggestions: bool = True


class SilentPauseRead(BaseModel):
    ordinal: int
    start_ms: int
    end_ms: int
    duration_ms: int


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
    started_at: datetime
    finished_at: datetime | None = None


class TrendPoint(BaseModel):
    session_id: int
    completed_at: datetime | None = None
    iu_recall_percent: float | None = None
    speech_rate: float | None = None
    articulation_rate: float | None = None
    pause_rate_per_100_words: float | None = None
    silent_pause_total_ms: int | None = None
    silent_pause_count: int | None = None
    syllable_count: int | None = None
    word_count: int | None = None


class TrendDelta(BaseModel):
    iu_recall_percent: float | None = None
    speech_rate: float | None = None
    articulation_rate: float | None = None
    pause_rate_per_100_words: float | None = None
    silent_pause_total_ms: float | None = None


class ParticipantTrendRead(BaseModel):
    participant_id: int
    display_name: str
    session_count: int
    series: list[TrendPoint] = []
    baseline: TrendPoint | None = None
    latest: TrendPoint | None = None
    deltas: TrendDelta | None = None
