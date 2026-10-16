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


def _exec_subprocess(argv: list[str], timeout: int) -> tuple[int, bytes, bytes]:
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return proc.returncode or 0, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        raise AudioToolMissing(f"{argv[0]} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioToolFailed(f"{argv[0]} timed out") from exc


async def _run(argv: list[str]) -> tuple[int, bytes, bytes]:
    return await asyncio.to_thread(_exec_subprocess, argv, settings.FFMPEG_TIMEOUT_SECONDS)


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


def parse_silences(text: str, duration_ms: int | None = None) -> list[tuple[int, int]]:
    """Parse silencedetect output into (start_ms, end_ms) intervals.

    Handles edge cases:
    - Leading silence: if silence_end occurs before any silence_start, silence started at 0ms.
    - Trailing silence: if silence_start occurs without a following silence_end (common at EOF),
      the silence interval continues up to duration_ms if known.
    """
    starts = [round(float(s) * 1000) for s in _SILENCE_START_RE.findall(text)]
    ends = [round(float(e) * 1000) for e in _SILENCE_END_RE.findall(text)]

    pairs: list[tuple[int, int]] = []

    # Leading silence ending before the first start is logged
    if len(ends) > len(starts) and ends and (not starts or ends[0] < starts[0]):
        pairs.append((0, max(0, ends.pop(0))))

    # Matched start-end pairs
    for s, e in zip(starts, ends):
        pairs.append((max(0, s), max(0, e)))

    # Trailing silence without an explicit silence_end at EOF
    if len(starts) > len(ends) and duration_ms is not None:
        unmatched_start = starts[len(ends)]
        end_ms = max(unmatched_start, duration_ms)
        pairs.append((max(0, unmatched_start), max(0, end_ms)))

    return pairs


async def detect_silences(path: Path, duration_ms: int | None = None) -> list[tuple[int, int]]:
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
    text = stderr.decode(errors="replace")
    starts = _SILENCE_START_RE.findall(text)
    ends = _SILENCE_END_RE.findall(text)
    if code != 0 and not starts:
        raise AudioToolFailed(f"ffmpeg exit {code}: {text[-200:]}")

    if len(starts) > len(ends) and duration_ms is None:
        try:
            duration_ms = await probe_duration_ms(path)
        except Exception:
            pass

    return parse_silences(text, duration_ms=duration_ms)
