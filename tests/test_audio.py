from app.services.audio import _SILENCE_END_RE, _SILENCE_START_RE, parse_silences
from app.services.speech_metrics import compute_speech_metrics


def test_silence_regex() -> None:
    sample_ffmpeg_stderr = """
    [silencedetect @ 0000021b] silence_start: 1.25
    [silencedetect @ 0000021b] silence_end: 2.75 | silence_duration: 1.50
    [silencedetect @ 0000021b] silence_start: 5.102
    [silencedetect @ 0000021b] silence_end: 6.000 | silence_duration: 0.898
    """
    starts = [float(s) for s in _SILENCE_START_RE.findall(sample_ffmpeg_stderr)]
    ends = [float(e) for e in _SILENCE_END_RE.findall(sample_ffmpeg_stderr)]
    assert starts == [1.25, 5.102]
    assert ends == [2.75, 6.000]


def test_parse_silences_standard() -> None:
    stderr = """
    silence_start: 1.25
    silence_end: 2.75 | silence_duration: 1.50
    silence_start: 5.0
    silence_end: 6.0 | silence_duration: 1.0
    """
    pairs = parse_silences(stderr, duration_ms=10000)
    assert pairs == [(1250, 2750), (5000, 6000)]


def test_parse_silences_trailing_without_end() -> None:
    # Audio ends in silence without ffmpeg printing silence_end
    stderr = """
    silence_start: 1.0
    silence_end: 2.5 | silence_duration: 1.5
    silence_start: 7.5
    """
    pairs = parse_silences(stderr, duration_ms=10000)
    assert pairs == [(1000, 2500), (7500, 10000)]


def test_parse_silences_leading_without_start() -> None:
    # Audio starts in silence where silence_start: 0 was omitted
    stderr = """
    silence_end: 1.2 | silence_duration: 1.2
    silence_start: 4.0
    silence_end: 5.0 | silence_duration: 1.0
    """
    pairs = parse_silences(stderr, duration_ms=10000)
    assert pairs == [(0, 1200), (4000, 5000)]


def test_parse_silences_trailing_integrated_with_csap_metrics() -> None:
    # 10s audio: speech from 0 to 7s, then trailing silence 7s to 10s without silence_end
    stderr = """
    silence_start: 2.0
    silence_end: 3.0 | silence_duration: 1.0
    silence_start: 7.0
    """
    pairs = parse_silences(stderr, duration_ms=10000)
    assert pairs == [(2000, 3000), (7000, 10000)]

    metrics = compute_speech_metrics(
        file_duration_ms=10000,
        silences=pairs,
        transcript_text="halo selamat pagi dunia",
        filled_pause_tokens=set(),
    )
    # Trailing silence must be recognized (3000ms), leaving 7000ms speech duration
    assert metrics["tail_silence_ms"] == 3000
    assert metrics["speech_duration_ms"] == 7000
    assert metrics["silent_pause_total_ms"] == 1000
    assert metrics["phonation_ms"] == 6000
