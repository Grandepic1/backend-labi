"""Pratinjau deskripsi deret sesi seorang peserta (prototipe analysis-trend).

Menjalankan lapisan deskripsi di `app/services/trend_description.py` terhadap data
nyata, supaya bentuk keluarannya bisa dinilai sebelum disambungkan ke endpoint.

Berbeda dari `GET /participants/{id}/analysis-trend` yang sekarang, script ini
memasukkan **semua** sesi yang punya run analisis selesai, bukan hanya yang
sudah difinalkan. Alasannya: metrik bicara tidak butuh penilaian final, jadi
menunggu finalisasi hanya membuang data yang sudah ada. Penilaian final hanya
relevan untuk IU recall, dan itu dilaporkan terpisah lewat `n` per ukuran.

Pemakaian:
    .venv/Scripts/python.exe scripts/describe_trend.py --participant 4
    .venv/Scripts/python.exe scripts/describe_trend.py --participant 4 --json
    .venv/Scripts/python.exe scripts/describe_trend.py --participant 4 --only-final
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DEBUG", "False")

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.trend_description import build_description, build_plain_description  # noqa: E402

# Satu baris per sesi: metrik dari run analisis terakhir yang selesai.
#
# Cap waktunya memakai `recordings.created_at` — kapan rekaman diunggah, yaitu
# proksi terdekat untuk "kapan sesi ini terjadi". Ini penting: memakai
# COALESCE(s.completed_at, run.finished_at) seperti percobaan pertama membuat
# campur-aduk, karena sesi yang sudah difinalkan memakai waktu finalisasi
# sementara yang belum memakai waktu analisis dijalankan — sehingga rentang
# waktunya jadi artefak, bukan fakta.
#
# CATATAN TIMEZONE: `recordings.created_at` memakai server_default=func.now(),
# jadi tersimpan dalam waktu lokal server (UTC+7), bukan UTC. Kolom lain seperti
# `sessions.completed_at` disimpan dalam UTC. Selama belum diseragamkan, jangan
# mencampur keduanya dalam satu perhitungan; script ini konsisten memakai satu
# kolom saja.
_SERIES = text(
    """
    SELECT s.id AS session_id,
           s.participant_id AS participant_id,
           s.status AS session_status,
           rec.created_at AS recorded_upload_at,
           run.asr_model AS asr_model,
           a.iu_recall_percent AS iu_recall_percent,
           a.met_count AS met_count,
           a.total_iu AS total_iu,
           a.status AS assessment_status,
           m.speech_rate, m.articulation_rate, m.pause_rate_per_100_words,
           m.silent_pause_total_ms, m.silent_pause_mean_ms, m.silent_pause_median_ms,
           m.silent_pause_count, m.syllable_count, m.word_count
    FROM sessions s
    JOIN recordings rec ON rec.session_id = s.id AND rec.deleted_at IS NULL
    JOIN session_analysis_runs run
      ON run.id = (
          SELECT x.id FROM session_analysis_runs x
          WHERE x.session_id = s.id AND x.status = 'completed'
          ORDER BY x.id DESC LIMIT 1
      )
    LEFT JOIN session_speech_metrics m ON m.run_id = run.id
    LEFT JOIN session_assessments a ON a.session_id = s.id AND a.status = 'final'
    WHERE s.participant_id = :participant_id
    ORDER BY rec.created_at, s.id
    """
)


def load(participant_id: int, only_final: bool) -> list[dict]:
    engine = create_engine(settings.sqlalchemy_database_url)
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(_SERIES, {"participant_id": participant_id}).mappings().all()]
    if only_final:
        rows = [r for r in rows if r["assessment_status"] == "final"]
    return rows


def render(points: list[dict], description: dict) -> str:
    out: list[str] = []
    out.append(f"# Deskripsi deret — peserta {points[0]['participant_id']}\n")
    out.append("## Sesi yang dipakai\n")
    out.append("| sesi | rekaman diunggah | status | assessment | recall | speech rate | artic rate | model |")
    out.append("|---|---|---|---|---|---|---|---|")
    for p in points:
        out.append(
            f"| {p['session_id']} | {p['recorded_upload_at']} | {p['session_status']} | "
            f"{p['assessment_status'] or '—'} | "
            f"{('%.2f' % float(p['iu_recall_percent'])) if p['iu_recall_percent'] is not None else '—'} | "
            f"{('%.2f' % float(p['speech_rate'])) if p['speech_rate'] is not None else '—'} | "
            f"{('%.2f' % float(p['articulation_rate'])) if p['articulation_rate'] is not None else '—'} | "
            f"{p['asr_model'] or '—'} |"
        )
    out.append(
        "\nCap waktu memakai `recordings.created_at`, yang tersimpan dalam waktu lokal server "
        "(UTC+7) — bukan UTC. Lihat catatan timezone di docstring."
    )

    out.append("\n## Ringkasan per ukuran\n")
    out.append("| ukuran | n | rata-rata | SD | CV % | min | maks |")
    out.append("|---|---|---|---|---|---|---|")
    for s in description["summary"]:
        if not s["n"]:
            out.append(f"| {s['label']} | 0 | — | — | — | — | — |")
            continue
        out.append(
            f"| {s['label']} ({s['unit']}) | {s['n']} | {s['mean']:.2f} | "
            f"{('%.2f' % s['sd']) if s['sd'] is not None else '—'} | "
            f"{('%.1f' % s['cv']) if s['cv'] is not None else '—'} | "
            f"{s['min']:.2f} | {s['max']:.2f} |"
        )

    out.append("\n## Deskripsi\n")
    for line in description["statements"]:
        out.append(f"- {line}")
    out.append("\n## Catatan wajib\n")
    for line in description["caveats"]:
        out.append(f"- {line}")
    out.append(
        f"\nKlaim tren {'diizinkan' if description['trend_claim_allowed'] else 'DITOLAK'} "
        f"(rentang {description['span_days']} hari)."
    )
    return "\n".join(out)


def render_plain(points: list[dict], plain: dict) -> str:
    out: list[str] = [f"# Versi bahasa sehari-hari — peserta {points[0]['participant_id']}\n"]
    for line in plain["lines"]:
        out.append(f"- {line}")
    out.append("\n## Catatan\n")
    for line in plain["notes"]:
        out.append(f"- {line}")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--participant", type=int, required=True)
    parser.add_argument("--only-final", action="store_true", help="tiru perilaku endpoint sekarang (butuh assessment final)")
    parser.add_argument("--json", action="store_true", help="cetak JSON mentah saja")
    parser.add_argument("--plain", action="store_true", help="versi bahasa sehari-hari untuk pendamping/pengguna")
    parser.add_argument("--self-view", action="store_true", help="dengan --plain: pembacanya orangnya sendiri (\"Anda\")")
    args = parser.parse_args()

    points = load(args.participant, args.only_final)
    if not points:
        print(f"Peserta {args.participant} tidak punya sesi dengan run analisis selesai.", file=sys.stderr)
        raise SystemExit(1)
    if args.plain:
        plain = build_plain_description(points, timestamp_key="recorded_upload_at", self_view=args.self_view)
        print(json.dumps(plain, indent=2, ensure_ascii=False, default=str) if args.json else render_plain(points, plain))
        return
    description = build_description(points, timestamp_key="recorded_upload_at")
    print(json.dumps(description, indent=2, ensure_ascii=False, default=str) if args.json else render(points, description))


main()
