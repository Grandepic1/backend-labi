from decimal import Decimal

from app.services.speech_metrics import (
    QUALITY_NO_TRANSCRIPT,
    QUALITY_TOO_SHORT,
    _count_tokens,
    compute_log_pause_metrics,
    compute_speech_metrics,
    count_syllables,
    internal_pauses,
    tokenize,
)


def test_count_syllables() -> None:
    assert count_syllables("makan") == 2
    assert count_syllables("pantai") == 2  # 'ai' diphthong
    assert count_syllables("kerbau") == 2  # 'au' diphthong
    assert count_syllables("sepeda") == 3
    assert count_syllables("mengelilingi") == 5


def test_tokenize() -> None:
    tokens = tokenize("Ibu pergi ke pasar, membeli sayur-mayur!")
    assert "pasar" in tokens
    assert "sayur" in tokens
    assert "mayur" in tokens


def test_count_tokens_and_fillers() -> None:
    tokens = ["ibu", "pergi", "ee", "ke", "pasar", "hmm"]
    filled_set = {"ee", "hmm"}
    words, syllables, filled = _count_tokens(tokens, filled_set)
    assert words == 4
    assert filled == 2
    assert syllables > 0


def test_internal_pauses_edge_tolerance() -> None:
    # Lead silence at start <= 100ms: (0, 500)
    # Tail silence near end >= 9900ms: (9500, 10000)
    # Internal silence: (3000, 4000)
    silences = [(0, 500), (3000, 4000), (9500, 10000)]
    internal = internal_pauses(10000, silences)
    assert internal == [(3000, 4000)]


def test_compute_speech_metrics_short_audio() -> None:
    res = compute_speech_metrics(
        file_duration_ms=800,
        silences=[],
        transcript_text="halo",
        filled_pause_tokens=set(),
    )
    assert res["quality_flag"] == QUALITY_TOO_SHORT
    assert res["speech_rate"] is None


def test_compute_speech_metrics_no_transcript() -> None:
    res = compute_speech_metrics(
        file_duration_ms=5000,
        silences=[],
        transcript_text="",
        filled_pause_tokens=set(),
    )
    assert res["quality_flag"] == QUALITY_NO_TRANSCRIPT
    assert res["speech_rate"] is None


def test_compute_speech_metrics_valid_csap() -> None:
    # 10s audio, 1 internal pause of 1000ms (from 4000 to 5000)
    # Speech duration = 10000ms. Phonation = 9000ms.
    # Transcript: "ibu pergi ke pasar" -> 4 words, 7 syllables (2 + 2 + 1 + 2)
    silences = [(4000, 5000)]
    res = compute_speech_metrics(
        file_duration_ms=10000,
        silences=silences,
        transcript_text="ibu pergi ke pasar",
        filled_pause_tokens=set(),
    )
    assert res["quality_flag"] is None
    assert res["speech_duration_ms"] == 10000
    assert res["phonation_ms"] == 9000
    assert res["silent_pause_count"] == 1
    assert res["silent_pause_total_ms"] == 1000
    assert res["silent_pause_mean_ms"] == Decimal("1000.00")
    # Syllables = 7
    # Speech rate (syllables/min) = 7 * 60,000 / 10,000 = 42.00
    # Articulation rate (syllables/min over phonation) = 7 * 60,000 / 9,000 = 46.67
    assert res["speech_rate"] == Decimal("42.00")
    assert res["articulation_rate"] == Decimal("46.67")
    # Pause rate per 100 words = 1 * 100 / 4 = 25.00
    assert res["pause_rate_per_100_words"] == Decimal("25.00")
    # CSAP log metrics: ln(1000) = 6.9077 -> 6.91
    assert res["log_metrics"]["mean"] == Decimal("6.91")
    assert res["log_metrics"]["median"] == Decimal("6.91")
    assert res["log_metrics"]["sd"] is None
    assert res["log_metrics"]["total"] == Decimal("6.91")


def test_compute_log_pause_metrics() -> None:
    empty = compute_log_pause_metrics([])
    assert empty == {"mean": None, "median": None, "sd": None, "total": None}

    single = compute_log_pause_metrics([1000])
    assert single["mean"] == Decimal("6.91")
    assert single["median"] == Decimal("6.91")
    assert single["sd"] is None
    assert single["total"] == Decimal("6.91")

    # [1000, 2000, 3000]: ln is approx 6.9078, 7.6009, 8.0064
    # mean = 7.5050... -> 7.51, median = 7.60, sd = 0.56, total = ln(6000) = 8.70
    multi = compute_log_pause_metrics([1000, 2000, 3000])
    assert multi["mean"] == Decimal("7.51")
    assert multi["median"] == Decimal("7.60")
    assert multi["sd"] == Decimal("0.56")
    assert multi["total"] == Decimal("8.70")
