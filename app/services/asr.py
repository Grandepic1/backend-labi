from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# On Windows, ensure nvidia runtime DLLs (cublas, cudnn) are discoverable by ctranslate2
if sys.platform == "win32":
    for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
        _bin_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia" / _sub / "bin"
        if _bin_dir.is_dir():
            try:
                os.add_dll_directory(str(_bin_dir))
            except Exception:
                pass
            os.environ["PATH"] = str(_bin_dir) + os.pathsep + os.environ.get("PATH", "")

from faster_whisper import WhisperModel

from app.core.config import settings

logger = logging.getLogger("app.analysis")


class AsrModelUnavailable(RuntimeError):
    pass


class AsrTimeout(RuntimeError):
    pass


class AsrFailed(RuntimeError):
    pass


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


def _decode(model: WhisperModel, path: str, language: str | None) -> str:
    # The segment generator is lazy: it must be consumed inside the worker
    # thread, otherwise decoding blocks the event loop.
    segments, _info = model.transcribe(
        path,
        language=language,
        beam_size=settings.ASR_BEAM_SIZE,
        vad_filter=settings.ASR_VAD_FILTER,
    )
    return "".join(segment.text for segment in segments).strip()


async def transcribe(path: Path) -> str:
    model = await _get_model()
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_decode, model, str(path), settings.ASR_LANGUAGE or None),
            timeout=settings.ASR_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise AsrTimeout(f"transcription exceeded {settings.ASR_TIMEOUT_SECONDS}s") from exc
    if not text:
        raise AsrFailed("no speech recognized")
    return text
