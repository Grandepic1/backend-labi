from __future__ import annotations

import math
import re
import statistics
from decimal import ROUND_HALF_UP, Decimal

# Vowel-nucleus approximation of Indonesian syllabification.
VOWELS = set("aeiou")
DIPHTHONGS = {"ai", "au", "oi", "ei"}

ANALYSIS_METHOD = "ffmpeg_silencedetect_v1"

QUALITY_TOO_SHORT = "too_short"
QUALITY_NO_TRANSCRIPT = "no_transcript"

# Below these the rates are meaningless rather than merely noisy.
MIN_SPEECH_DURATION_MS = 1000
MIN_PHONATION_MS = 500
# A silence touching the first/last 100 ms is recorder lead-in/lead-out,
# not a pause produced by the speaker.
EDGE_TOLERANCE_MS = 100

_TOKEN_RE = re.compile(r"[0-9A-Za-z\u00C0-\u024F]+")
_NON_LETTER_RE = re.compile(r"[^a-z]")

_TWO_PLACES = Decimal("0.01")


def count_syllables(word: str) -> int:
    w = "".join(ch for ch in word.lower() if ch.isalpha())
    nuclei, i = 0, 0
    while i < len(w):
        if w[i] not in VOWELS:
            i += 1
            continue
        nuclei += 1
        j = i + 1
        if (
            j < len(w)
            and w[j] in VOWELS
            and w[i : j + 1] in DIPHTHONGS
            and not (i == 0 and j + 1 < len(w) and w[j + 1] not in VOWELS)
        ):
            i = j
        i += 1
    return nuclei


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _quantize(value: float) -> Decimal:
    return Decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _count_tokens(tokens: list[str], filled_pause_tokens: set[str]) -> tuple[int, int, int]:
    words = 0
    syllables = 0
    filled = 0
    for token in tokens:
        key = _NON_LETTER_RE.sub("", token.lower())
        if key and key in filled_pause_tokens:
            filled += 1
            continue
        words += 1
        syllables += count_syllables(token)
    return words, syllables, filled


def internal_pauses(file_duration_ms: int, silences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    has_lead = bool(silences) and silences[0][0] <= EDGE_TOLERANCE_MS
    has_tail = bool(silences) and silences[-1][1] >= file_duration_ms - EDGE_TOLERANCE_MS
    return [(int(s), int(e)) for s, e in silences[1 if has_lead else 0 : len(silences) - 1 if has_tail else len(silences)]]


def compute_log_pause_metrics(durations_ms: list[int]) -> dict[str, Decimal | None]:
    """Computes log-normal distribution metrics (ln) for silent pauses per CSAP protocol (Angelopoulou et al., 2024)."""
    positives = [d for d in durations_ms if d > 0]
    if not positives:
        return {"mean": None, "median": None, "sd": None, "total": None}
    log_vals = [math.log(d) for d in positives]
    total_ms = sum(positives)
    return {
        "mean": _quantize(statistics.fmean(log_vals)),
        "median": _quantize(statistics.median(log_vals)),
        "sd": _quantize(statistics.stdev(log_vals)) if len(log_vals) > 1 else None,
        "total": _quantize(math.log(total_ms)) if total_ms > 0 else None,
    }


def compute_speech_metrics(
    *,
    file_duration_ms: int,
    silences: list[tuple[int, int]],
    transcript_text: str | None,
    filled_pause_tokens: set[str],
) -> dict:
    has_lead = bool(silences) and silences[0][0] <= EDGE_TOLERANCE_MS
    has_tail = bool(silences) and silences[-1][1] >= file_duration_ms - EDGE_TOLERANCE_MS
    lead_silence_ms = int(silences[0][1]) if has_lead else 0
    tail_silence_ms = int(file_duration_ms - silences[-1][0]) if has_tail else 0
    speech_duration_ms = max(0, int(file_duration_ms) - lead_silence_ms - tail_silence_ms)

    internal = internal_pauses(file_duration_ms, silences)
    durations = [end - start for start, end in internal]
    silent_pause_count = len(durations)
    silent_pause_total_ms = sum(durations)
    phonation_ms = max(0, speech_duration_ms - silent_pause_total_ms)

    text = (transcript_text or "").strip()
    if text:
        word_count, syllable_count, filled_pause_count = _count_tokens(
            tokenize(text), filled_pause_tokens
        )
    else:
        word_count = syllable_count = filled_pause_count = 0

    if speech_duration_ms < MIN_SPEECH_DURATION_MS or phonation_ms < MIN_PHONATION_MS:
        quality_flag: str | None = QUALITY_TOO_SHORT
    elif not text:
        quality_flag = QUALITY_NO_TRANSCRIPT
    else:
        quality_flag = None

    def mean_ms() -> Decimal | None:
        return _quantize(statistics.fmean(durations)) if durations else None

    def median_ms() -> Decimal | None:
        return _quantize(statistics.median(durations)) if durations else None

    def sd_ms() -> Decimal | None:
        return _quantize(statistics.stdev(durations)) if len(durations) > 1 else None

    # Rates are undefined without a usable transcript, and meaningless on a
    # clipping-short window.
    rates_ok = quality_flag is None

    def per_minute(count: int, window_ms: int) -> Decimal | None:
        if not rates_ok or window_ms <= 0 or count <= 0:
            return None
        return _quantize(count * 60_000 / window_ms)

    def per_100_words() -> Decimal | None:
        if not rates_ok or word_count <= 0:
            return None
        return _quantize(silent_pause_count * 100 / word_count)

    return {
        "analysis_method": ANALYSIS_METHOD,
        "file_duration_ms": int(file_duration_ms),
        "lead_silence_ms": lead_silence_ms,
        "tail_silence_ms": tail_silence_ms,
        "speech_duration_ms": speech_duration_ms,
        "phonation_ms": phonation_ms,
        "silent_pause_total_ms": silent_pause_total_ms,
        "silent_pause_count": silent_pause_count,
        "silent_pause_mean_ms": mean_ms(),
        "silent_pause_median_ms": median_ms(),
        "silent_pause_sd_ms": sd_ms(),
        "speech_rate": per_minute(syllable_count, speech_duration_ms),
        "articulation_rate": per_minute(syllable_count, phonation_ms),
        "speech_rate_wpm": per_minute(word_count, speech_duration_ms),
        "articulation_rate_wpm": per_minute(word_count, phonation_ms),
        "pause_rate_per_100_words": per_100_words(),
        "syllable_count": syllable_count,
        "word_count": word_count,
        "filled_pause_count": filled_pause_count,
        "quality_flag": quality_flag,
        "silent_pause_durations_ms": durations,
        "log_metrics": compute_log_pause_metrics(durations),
    }
