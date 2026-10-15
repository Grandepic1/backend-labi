"""Ekspor CSAP Table 2 item 1-10 dari run metrik terakhir tiap sesi.

Menghasilkan tabel siap tempel ke paper: satu baris per sesi, satu kolom per
variabel, plus ringkasan rata-rata ± SD dan nilai tertransformasi ln.

Penting: angka-angka ini terikat pada model ASR yang menghasilkannya. Setelah
model diganti, jalankan `scripts/rebuild_analysis.py` lebih dulu, lalu script
ini lagi — kalau tidak, tabelnya akan mencampur dua model.

CSAP §2.3 mewajibkan nilai jeda ditransformasi ln sebelum analisis statistik
(distribusi log-normal, Campione & Véronis). Tabel B menyediakannya; nilai
mentah di tabel A tetap dalam milidetik sesuai definisi Tabel 2.

Pemakaian:
    .venv/Scripts/python.exe scripts/export_csap_table.py
    .venv/Scripts/python.exe scripts/export_csap_table.py --model large-v3
    .venv/Scripts/python.exe scripts/export_csap_table.py --exclude 5,6
    .venv/Scripts/python.exe scripts/export_csap_table.py --format csv > csap.csv
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DEBUG", "False")

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402

# Satu baris per sesi: run metrik terakhir, plus peserta dan judul cerita.
# Peserta diambil supaya script bisa menyatakan sendiri berapa penutur yang
# sebenarnya ada di tabel — beberapa sesi sering kali milik orang yang sama,
# dan menyebutnya "n sesi" sebagai "n peserta" adalah klaim yang salah.
_LATEST = text(
    """
    SELECT m.*, s.participant_id, p.display_name AS participant_name, s.created_at AS session_created
    FROM session_speech_metrics m
    JOIN (SELECT session_id, MAX(id) AS mid FROM session_speech_metrics GROUP BY session_id) t
      ON t.mid = m.id
    JOIN sessions s ON s.id = m.session_id
    LEFT JOIN participants p ON p.id = s.participant_id
    ORDER BY m.session_id
    """
)

# (kolom, nomor CSAP, judul, satuan, apakah nilai jeda yang perlu ln)
MEASURES: list[tuple[str, str, str, str, bool]] = [
    ("speech_duration_ms", "1", "Total duration of speech", "ms", False),
    ("phonation_ms", "2", "Total duration of phonation", "ms", False),
    ("silent_pause_total_ms", "3", "Total duration of silent pauses", "ms", True),
    ("silent_pause_mean_ms", "4", "Mean duration of silent pauses", "ms", True),
    ("silent_pause_median_ms", "5", "Median duration of silent pauses", "ms", True),
    ("syllable_count", "6", "Total number of syllables", "n", False),
    ("word_count", "7", "Total number of words", "n", False),
    ("speech_rate", "8", "Speech rate", "syl/min", False),
    ("articulation_rate", "9", "Articulation rate", "syl/min", False),
    ("pause_rate_per_100_words", "10", "Pause frequency", "per 100 words", False),
]

EXTRA: list[tuple[str, str, str]] = [
    ("silent_pause_count", "Silent pause count", "n"),
    ("silent_pause_sd_ms", "SD of silent pauses", "ms"),
    ("filled_pause_count", "Filled pause count (from text)", "n"),
    ("filled_pause_total_ms", "Filled pause duration (from timeline)", "ms"),
    ("speech_rate_wpm", "Speech rate (words)", "wpm"),
    ("articulation_rate_wpm", "Articulation rate (words)", "wpm"),
]


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.{digits}f}"


def _ln(value) -> float | None:
    v = _num(value)
    return math.log(v) if v and v > 0 else None


def load(model: str, exclude: set[int], include_flagged: bool) -> tuple[list[dict], list[str]]:
    engine = create_engine(settings.sqlalchemy_database_url)
    rows: list[dict] = []
    notes: list[str] = []
    with engine.connect() as conn:
        for raw in conn.execute(_LATEST).mappings().all():
            params = raw["params"]
            if isinstance(params, str):
                params = json.loads(params) if params else {}
            params = params or {}
            if params.get("asr_model") != model:
                continue
            if raw["session_id"] in exclude:
                notes.append(f"sesi {raw['session_id']} dikecualikan (--exclude)")
                continue
            if raw["quality_flag"] and not include_flagged:
                notes.append(
                    f"sesi {raw['session_id']} dikecualikan (quality_flag={raw['quality_flag']})"
                )
                continue
            row = dict(raw)
            row["_params"] = params
            rows.append(row)
    return rows, notes


def render_markdown(rows: list[dict], model: str, notes: list[str]) -> str:
    out: list[str] = []
    ids = [r["session_id"] for r in rows]
    out.append("# CSAP Table 2 — item 1-10\n")
    out.append(f"Model ASR: `{model}` · sesi: {', '.join(str(i) for i in ids)} ({len(ids)} sesi)\n")
    participants = {r["participant_id"] for r in rows}
    if len(participants) == 1:
        name = next((r.get("participant_name") for r in rows if r.get("participant_name")), "?")
        out.append(
            f"Penutur: **1** ({name}) — jadi semua baris di bawah adalah **pengulangan oleh "
            f"satu orang**, bukan sampel antar-peserta. Jangan tulis \"n={len(rows)} peserta\".\n"
        )
    else:
        out.append(f"Penutur: **{len(participants)}** berbeda di {len(rows)} sesi.\n")
    out.append(
        "> **Angka ini terikat pada model ASR di atas.** Setelah model diganti, jalankan\n"
        "> `scripts/rebuild_analysis.py` lebih dulu lalu script ini lagi. Jangan mencampur\n"
        "> baris dari dua model dalam satu tabel.\n"
    )
    if notes:
        out.append("Catatan: " + "; ".join(notes) + ".\n")

    header = "| sesi | " + " | ".join(f"{num}. {title} ({unit})" for _, num, title, unit, _ in MEASURES) + " |"
    out.append("## A. Nilai mentah per sesi\n")
    out.append(header)
    out.append("|---" * (len(MEASURES) + 1) + "|")
    for r in rows:
        cells = [_fmt(_num(r[col])) for col, *_ in MEASURES]
        out.append(f"| **{r['session_id']}** | " + " | ".join(cells) + " |")

    out.append("\n## B. Nilai jeda tertransformasi ln (CSAP §2.3)\n")
    ln_cols = [(c, n, t, u) for c, n, t, u, is_pause in MEASURES if is_pause]
    out.append("| sesi | " + " | ".join(f"ln({t})" for _, _, t, _ in ln_cols) + " |")
    out.append("|---" * (len(ln_cols) + 1) + "|")
    for r in rows:
        cells = [_fmt(_ln(r[col]), 4) for col, *_ in ln_cols]
        out.append(f"| **{r['session_id']}** | " + " | ".join(cells) + " |")

    out.append("\n## C. Ringkasan lintas sesi\n")
    out.append("| variabel | n | rata-rata | SD | CV % | min | maks |")
    out.append("|---|---|---|---|---|---|---|")
    for col, num, title, unit, _ in MEASURES:
        values = [v for v in (_num(r[col]) for r in rows) if v is not None]
        if not values:
            out.append(f"| {num}. {title} | 0 | — | — | — | — | — |")
            continue
        mean = statistics.fmean(values)
        sd = statistics.stdev(values) if len(values) > 1 else None
        # CV = SD/rata-rata. Kalau semua baris satu penutur, ini ukuran kestabilan
        # pengukuran pada orang yang sama, bukan keragaman antar-orang.
        cv = (sd / mean * 100) if (sd is not None and mean) else None
        out.append(
            f"| {num}. {title} ({unit}) | {len(values)} | {_fmt(mean)} | "
            f"{_fmt(sd)} | {_fmt(cv, 1)} | {_fmt(min(values))} | {_fmt(max(values))} |"
        )

    out.append("\n## D. Kolom pendukung\n")
    out.append("| sesi | " + " | ".join(f"{t} ({u})" for _, t, u in EXTRA) + " |")
    out.append("|---" * (len(EXTRA) + 1) + "|")
    for r in rows:
        cells = [_fmt(_num(r[col])) for col, *_ in EXTRA]
        out.append(f"| **{r['session_id']}** | " + " | ".join(cells) + " |")

    timed = [r["session_id"] for r in rows if (r["_params"] or {}).get("filled_pause_timed")]
    if len(timed) < len(rows):
        missing = [r["session_id"] for r in rows if r["session_id"] not in timed]
        out.append(
            f"\n**Item 2 tidak terukur penuh** untuk sesi {', '.join(str(i) for i in missing)}: "
            "tidak ada word timeline, jadi istilah jeda terisi tidak tersedia dan `phonation_ms` "
            "adalah nilai berbasis-jeda-senyap-saja (overestimate)."
        )
    return "\n".join(out) + "\n"


def render_csv(rows: list[dict]) -> str:
    cols = [c for c, *_ in MEASURES] + [c for c, *_ in EXTRA]
    out = ["session_id," + ",".join(cols)]
    for r in rows:
        out.append(
            str(r["session_id"]) + "," + ",".join("" if _num(r[c]) is None else str(_num(r[c])) for c in cols)
        )
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=settings.ASR_MODEL, help="hanya baris dengan asr_model ini")
    parser.add_argument("--exclude", default="", help="id sesi yang dibuang, mis. 5,6 (fixture)")
    parser.add_argument("--include-flagged", action="store_true", help="ikutkan sesi dengan quality_flag")
    parser.add_argument("--format", choices=("md", "csv"), default="md")
    args = parser.parse_args()

    exclude = {int(x) for x in args.exclude.split(",") if x.strip()}
    rows, notes = load(args.model, exclude, args.include_flagged)
    if not rows:
        print(f"Tidak ada sesi dengan metrik dari model `{args.model}`. "
              "Jalankan scripts/rebuild_analysis.py lebih dulu.", file=sys.stderr)
        raise SystemExit(1)
    print(render_csv(rows) if args.format == "csv" else render_markdown(rows, args.model, notes))


main()
