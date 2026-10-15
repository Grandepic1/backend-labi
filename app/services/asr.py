from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

from app.core.config import settings

logger = logging.getLogger("app.analysis")


class AsrModelUnavailable(RuntimeError):
    pass


class AsrTimeout(RuntimeError):
    pass


class AsrFailed(RuntimeError):
    pass


@dataclass(slots=True)
class AsrWord:
    word: str
    start_ms: int
    end_ms: int
    probability: float | None


@dataclass(slots=True)
class AsrSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str
    words: list[AsrWord] = field(default_factory=list)


@dataclass(slots=True)
class AsrResult:
    text: str
    segments: list[AsrSegment] = field(default_factory=list)
    # Duration reported by the decoder: a free cross-check against ffprobe.
    duration_ms: int | None = None
    language: str | None = None
    language_probability: float | None = None


_model: WhisperModel | None = None
_lock = asyncio.Lock()


def _load_model() -> WhisperModel:
    root = Path(settings.ASR_MODEL_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return WhisperModel(
        settings.ASR_MODEL,
        device=settings.ASR_DEVICE,
        compute_type=settings.ASR_COMPUTE_TYPE,
        download_root=str(root),
    )


async def _get_model() -> WhisperModel:
    global _model
    if _model is not None:
        return _model
    async with _lock:
        # Second check: another task may have loaded it while we waited.
        if _model is None:
            try:
                _model = await asyncio.to_thread(_load_model)
            except Exception as exc:  # noqa: BLE001 — no weights, bad device, OOM…
                raise AsrModelUnavailable(str(exc)[:500]) from exc
            logger.info("asr model loaded: %s", settings.ASR_MODEL)
    return _model


def _ms(seconds: float | None) -> int:
    return 0 if seconds is None else round(seconds * 1000)


def _decode(model: WhisperModel, path: str, language: str | None) -> AsrResult:
    # The segment generator is lazy: it must be consumed inside the worker
    # thread, otherwise decoding blocks the event loop.
    segments, info = model.transcribe(
        path,
        language=language,
        beam_size=settings.ASR_BEAM_SIZE,
        vad_filter=settings.ASR_VAD_FILTER,
        word_timestamps=settings.ASR_WORD_TIMESTAMPS,
    )
    raw_parts: list[str] = []
    collected: list[AsrSegment] = []
    for index, segment in enumerate(segments):
        raw_parts.append(segment.text)
        collected.append(
            AsrSegment(
                index=index,
                start_ms=_ms(segment.start),
                end_ms=_ms(segment.end),
                text=segment.text.strip(),
                words=[
                    AsrWord(
                        word=word.word,
                        start_ms=_ms(word.start),
                        end_ms=_ms(word.end),
                        probability=None if word.probability is None else round(word.probability, 4),
                    )
                    for word in (segment.words or [])
                ],
            )
        )
    # Joined exactly as before so the transcript text is unchanged by the
    # addition of timestamps.
    return AsrResult(
        text="".join(raw_parts).strip(),
        segments=collected,
        duration_ms=_ms(getattr(info, "duration", None)),
        language=getattr(info, "language", None),
        language_probability=getattr(info, "language_probability", None),
    )


def _detect_language(model: WhisperModel, path: str) -> tuple[str, float]:
    audio = decode_audio(path, sampling_rate=16000)
    language, probability, _all_probs = model.detect_language(audio, vad_filter=settings.ASR_VAD_FILTER)
    return language, float(probability)


async def transcribe(path: Path) -> AsrResult:
    model = await _get_model()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_decode, model, str(path), settings.ASR_LANGUAGE or None),
            timeout=settings.ASR_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise AsrTimeout(f"transcription exceeded {settings.ASR_TIMEOUT_SECONDS}s") from exc
    if not result.text:
        raise AsrFailed("no speech recognized")

    # With a forced ASR_LANGUAGE, Whisper skips identification and reports the
    # forced value back, so info.language carries no signal at all. A separate
    # detection pass is the only way to notice a transcript that came out in
    # another language. Quality control only: never fail the run over it.
    if settings.ASR_DETECT_LANGUAGE and settings.ASR_LANGUAGE:
        try:
            language, probability = await asyncio.wait_for(
                asyncio.to_thread(_detect_language, model, str(path)),
                timeout=settings.ASR_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — QC only, never fatal
            logger.warning("language detection failed for %s: %s", path.name, type(exc).__name__)
        else:
            result.language, result.language_probability = language, probability
    return result
