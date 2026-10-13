from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.core.config import settings


class AudioToolMissing(RuntimeError):
    pass


class AudioToolFailed(RuntimeError):
    pass


_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


async def _run(argv: list[str]) -> tuple[int, bytes, bytes]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AudioToolMissing(f"{argv[0]} not found") from exc
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.FFMPEG_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AudioToolFailed(f"{argv[0]} timed out") from exc
    return proc.returncode or 0, stdout, stderr


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


async def detect_silences(path: Path) -> list[tuple[int, int]]:
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
            f"silencedetect=noise={settings.PAUSE_NOISE_DB}dB:d={settings.PAUSE_MIN_MS / 1000}",
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
