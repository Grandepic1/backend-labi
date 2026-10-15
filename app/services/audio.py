from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

from app.core.config import settings


class AudioToolMissing(RuntimeError):
    pass


class AudioToolFailed(RuntimeError):
    pass


_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")
_MAX_VOLUME_RE = re.compile(r"max_volume:\s*(-?[\d.]+) dB")


def _run_blocking(argv: list[str]) -> tuple[int, bytes, bytes]:
    """Invoke the audio tool on a worker thread.

    ``asyncio.create_subprocess_exec`` cannot be used here. On Windows, uvicorn
    selects a ``SelectorEventLoop`` whenever it runs with ``reload`` (which is
    the case in development), and that loop does not implement subprocess
    support at all -- it raises a bare ``NotImplementedError`` with no message,
    which surfaced only as an opaque ``INTERNAL`` analysis failure. A blocking
    ``subprocess.run`` on a worker thread behaves the same on every platform and
    every event loop, and its timeout actually terminates the child process.
    """
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=settings.FFMPEG_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise AudioToolMissing(f"{argv[0]} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioToolFailed(f"{argv[0]} timed out") from exc
    return completed.returncode or 0, completed.stdout, completed.stderr


async def _run(argv: list[str]) -> tuple[int, bytes, bytes]:
    return await asyncio.to_thread(_run_blocking, argv)


async def probe_duration_ms(path: Path) -> int:
    code, stdout, stderr = await _run(
        [
            settings.FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if code != 0:
        raise AudioToolFailed(f"ffprobe exit {code}: {stderr.decode(errors='replace')[:200]}")
    raw = stdout.decode(errors="replace").strip()
    try:
        return round(float(raw) * 1000)
    except ValueError as exc:
        raise AudioToolFailed("duration unavailable") from exc


async def measure_peak_db(path: Path) -> float | None:
    """Peak sample level of the file, in dBFS."""
    code, _, stderr = await _run(
        [
            settings.FFMPEG_BIN,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
    )
    text = stderr.decode(errors="replace")
    match = _MAX_VOLUME_RE.search(text)
    if code != 0 or match is None:
        return None
    return float(match.group(1))


async def resolve_noise_db(path: Path) -> float:
    """The silencedetect floor to use for this file.

    A single absolute floor cannot serve recordings that differ in headroom.
    Measured on the real sessions, a fixed -30 dB reported 0 silent pauses for
    session 26 and 41 for session 22 -- the same threshold, two contradictory
    answers. Deriving the floor from the file's own peak keeps the detector
    proportional to the recording instead of to the recorder.
    """
    if not settings.PAUSE_ADAPTIVE_NOISE:
        return settings.PAUSE_NOISE_DB
    peak = await measure_peak_db(path)
    if peak is None:
        return settings.PAUSE_NOISE_DB
    return min(
        settings.PAUSE_NOISE_MAX_DB,
        max(settings.PAUSE_NOISE_MIN_DB, peak - settings.PAUSE_NOISE_MARGIN_DB),
    )


async def detect_silences(path: Path, noise_db: float | None = None) -> list[tuple[int, int]]:
    if noise_db is None:
        noise_db = await resolve_noise_db(path)
    code, _, stderr = await _run(
        [
            settings.FFMPEG_BIN,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            f"silencedetect=noise={noise_db}dB:d={settings.PAUSE_MIN_MS / 1000}",
            "-f",
            "null",
            "-",
        ]
    )
    # silencedetect reports a trailing silence_end of "inf" style values only
    # in unusual streams; a missing end is treated as the file end by callers
    # not needing it, so pairs are zipped strictly.
    text = stderr.decode(errors="replace")
    starts = _SILENCE_START_RE.findall(text)
    ends = _SILENCE_END_RE.findall(text)
    if code != 0 and not starts:
        raise AudioToolFailed(f"ffmpeg exit {code}: {text[-200:]}")
    pairs: list[tuple[int, int]] = []
    for start_raw, end_raw in zip(starts, ends):
        start_ms = round(float(start_raw) * 1000)
        end_ms = round(float(end_raw) * 1000)
        pairs.append((max(0, start_ms), max(0, end_ms)))
    return pairs
