from __future__ import annotations

import re
import statistics
from decimal import ROUND_HALF_UP, Decimal

# Vowel-nucleus approximation of Indonesian syllabification.
VOWELS = set("aeiou")
DIPHTHONGS = {"ai", "au", "oi", "ei"}

ANALYSIS_METHOD = "ffmpeg_silencedetect_v1"

QUALITY_TOO_SHORT = "too_short"
QUALITY_NO_TRANSCRIPT = "no_transcript"
QUALITY_LANGUAGE_MISMATCH = "language_mismatch"

# Below these the rates are meaningless rather than merely noisy.
MIN_SPEECH_DURATION_MS = 1000
MIN_PHONATION_MS = 500
# A silence touching the first/last 100 ms is recorder lead-in/lead-out,
# not a pause produced by the speaker.
EDGE_TOLERANCE_MS = 100

# Alphanumeric runs, plus a separator that sits *between* digits ("5", "1.000",
# "2,5"). Whisper writes Indonesian numerals as digits, so the separator has to
# be part of the token or "1.000" would be counted as two numbers.
_TOKEN_RE = re.compile(r"[0-9A-Za-z\u00C0-\u024F]+(?:[.,][0-9]+)*")
_NON_LETTER_RE = re.compile(r"[^a-z]")
_NUMERIC_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)*")

_TWO_PLACES = Decimal("0.01")

# --- Indonesian numeral spelling -------------------------------------------
# CSAP counts words and syllables over the orthographic transcription. A digit
# string contains no vowel nucleus, so counting "5" verbatim yielded zero
# syllables and silently deflated syllable_count along with both rates. Spelling
# the numeral out restores what the speaker actually uttered.
_UNIT_WORDS = (
    "nol",
    "satu",
    "dua",
    "tiga",
    "empat",
    "lima",
    "enam",
    "tujuh",
    "delapan",
    "sembilan",
)
_SCALE_WORDS = ((10**12, "triliun"), (10**9, "miliar"), (10**6, "juta"), (10**3, "ribu"))
# Beyond this a "number" is not a spoken quantity; leave the raw token alone.
_MAX_SPELLED_DIGITS = 15


def _spell_below_thousand(n: int) -> str:
    if n < 10:
        return _UNIT_WORDS[n]
    if n == 10:
        return "sepuluh"
    if n == 11:
        return "sebelas"
    if n < 20:
        return f"{_UNIT_WORDS[n - 10]} belas"
    if n < 100:
        tens, rest = divmod(n, 10)
        head = f"{_UNIT_WORDS[tens]} puluh"
        return f"{head} {_UNIT_WORDS[rest]}" if rest else head
    if n == 100:
        return "seratus"
    if n < 200:
        head, rest = "seratus", n - 100
    else:
        hundreds, rest = divmod(n, 100)
        head = f"{_UNIT_WORDS[hundreds]} ratus"
    return f"{head} {_spell_below_thousand(rest)}" if rest else head


def spell_number(n: int) -> str:
    if n == 0:
        return _UNIT_WORDS[0]
    if n < 0:
        return f"minus {spell_number(-n)}"
    parts: list[str] = []
    for value, name in _SCALE_WORDS:
        if n >= value:
            count, n = divmod(n, value)
            parts.append("seribu" if (value == 1000 and count == 1) else f"{spell_number(count)} {name}")
    if n:
        parts.append(_spell_below_thousand(n))
    return " ".join(parts)


def spell_numeric_token(token: str) -> str:
    """Spell a digit token the way an Indonesian speaker would say it.

    "." groups thousands and "," separates decimals (Indonesian convention),
    except that a lone "." followed by 1-2 digits is read as a decimal point,
    which is how a transcript normally writes "1.5".
    """
    whole, comma, fraction = token.partition(",")
    groups = whole.split(".")
    if len(groups) > 1 and not all(len(group) == 3 for group in groups[1:]):
        comma, fraction = ".", ".".join(groups[1:])
        groups = groups[:1]
    digits = "".join(groups)
    if not digits or len(digits) > _MAX_SPELLED_DIGITS:
        return token
    spelled = spell_number(int(digits))
    if comma and fraction:
        tail = " ".join(_UNIT_WORDS[int(d)] for d in fraction if d.isdigit())
        if tail:
            return f"{spelled} koma {tail}"
    return spelled


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
        if _NUMERIC_RE.fullmatch(token):
            # A numeral can spell out to several words ("2024" -> five), and
            # each of them carries its own vowel nuclei.
            for spelled in spell_numeric_token(token).split():
                words += 1
                syllables += count_syllables(spelled)
            continue
        words += 1
        syllables += count_syllables(token)
    return words, syllables, filled


def internal_pauses(file_duration_ms: int, silences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    has_lead = bool(silences) and silences[0][0] <= EDGE_TOLERANCE_MS
    has_tail = bool(silences) and silences[-1][1] >= file_duration_ms - EDGE_TOLERANCE_MS
    return [(int(s), int(e)) for s, e in silences[1 if has_lead else 0 : len(silences) - 1 if has_tail else len(silences)]]


def _field(obj, name: str, default=None):
    """Read one attribute from a dict or an object.

    The stored timeline is a list of dicts (JSON column), but the same helper
    has to work on the dataclasses when metrics are computed straight from an
    ASR result, so both shapes are accepted.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def filled_pause_spans(segments, filled_pause_tokens: set[str]) -> list[tuple[int, int]] | None:
    """Word-level time spans of the filled pauses, from the ASR word timeline.

    CSAP §2.3 annotates filled pauses only in order to remove them from the
    word count, but their *duration* is what separates table 2 item 2
    (phonation) from item 3 (silent pauses). Dropping the term overstates
    phonation and therefore understates articulation rate (item 9).

    The transcript text alone cannot supply this: a token with no timeline entry
    has no position in time. Returns None when there is no timeline at all,
    which is deliberately different from an empty list ("a timeline that
    contains no filled pause") — the caller stores the difference so a silent
    fallback is never mistaken for a measurement.
    """
    if not segments:
        return None
    spans: list[tuple[int, int]] = []
    for segment in segments:
        for word in _field(segment, "words") or []:
            key = _NON_LETTER_RE.sub("", str(_field(word, "word") or "").lower())
            if not key or key not in filled_pause_tokens:
                continue
            start, end = _field(word, "start_ms"), _field(word, "end_ms")
            if start is None or end is None:
                continue
            spans.append((int(start), int(end)))
    return spans


def compute_speech_metrics(
    *,
    file_duration_ms: int,
    silences: list[tuple[int, int]],
    transcript_text: str | None,
    filled_pause_tokens: set[str],
    transcript_language: str | None = None,
    expected_language: str | None = None,
    filled_spans: list[tuple[int, int]] | None = None,
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

    # CSAP item 2: phonation is speech minus *all* disfluencies, silent and
    # filled. `filled_spans is None` means the transcript carried no word
    # timeline, so the filled term is unknowable; phonation then falls back to
    # the silent-only value and is flagged as an overestimate rather than
    # silently mixed with measured rows.
    filled_durations = None if filled_spans is None else [end - start for start, end in filled_spans]
    filled_pause_total_ms = None if filled_durations is None else sum(filled_durations)
    phonation_ms = max(0, speech_duration_ms - silent_pause_total_ms - (filled_pause_total_ms or 0))

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
    elif (
        expected_language
        and transcript_language
        and transcript_language.lower() != expected_language.lower()
    ):
        # The syllable heuristic and the word list are Indonesian; running them
        # over a transcript in another language produces numbers that look fine
        # and mean nothing. Session 19 is the real case: English text for
        # Indonesian audio, scored without complaint.
        quality_flag = QUALITY_LANGUAGE_MISMATCH
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
        "filled_pause_total_ms": filled_pause_total_ms,
        "quality_flag": quality_flag,
        "silent_pause_durations_ms": durations,
        # Not a column: how many filled pauses the timeline could place in time,
        # next to the count read off the text. A gap between the two is the
        # honest measure of how much of item 2 is actually measured.
        "filled_pause_timed_count": None if filled_durations is None else len(filled_durations),
    }
