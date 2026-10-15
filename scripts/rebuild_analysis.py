"""Bangun ulang analisis untuk semua sesi: ASR + metrik bicara + saran IU.

Dipakai ketika model ASR diganti. Mengganti model mengubah teks transkrip itu
sendiri (word_timestamps saja sudah mengubah sesi 26 secara deterministik), dan
teks menentukan setiap hitungan kata/suku kata serta setiap penyelarasan jeda.
Karena itu satu dataset tidak boleh mencampur dua model: skrip ini menjalankan
ulang semuanya dengan konfigurasi ASR yang sedang aktif, dan menolak diam-diam
melewati sesi yang sudah pernah diproses dengan model yang sama kecuali diminta.

Transkrip bersifat append-only, jadi menjalankan ulang tidak menghapus apa pun:
transkrip lama tetap ada, dan `transcripts.asr_model` yang membedakannya.

Pemakaian:
    .venv/Scripts/python.exe scripts/rebuild_analysis.py --dry-run
    .venv/Scripts/python.exe scripts/rebuild_analysis.py
    .venv/Scripts/python.exe scripts/rebuild_analysis.py --sessions 26,27,28
    .venv/Scripts/python.exe scripts/rebuild_analysis.py --force
    .venv/Scripts/python.exe scripts/rebuild_analysis.py --no-iu   # lewati LLM
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The SQL echo that is useful while debugging the API turns a multi-session
# rebuild into thousands of lines of noise and interleaves with the summary
# table. The OS environment outranks .env in pydantic-settings, so this is
# scoped to this process only.
os.environ.setdefault("DEBUG", "False")

from sqlalchemy import text  # noqa: E402

from app.api.v1.routes.sessions import _execute_run  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.schemas.analysis import AnalysisRunIn  # noqa: E402

# Sesi yang punya rekaman aktif, beserta run terakhir yang selesai.
_TARGETS = text(
    """
    SELECT s.id AS session_id,
           s.status AS session_status,
           r.storage_key AS storage_key,
           (SELECT MAX(x.id) FROM session_analysis_runs x
             WHERE x.session_id = s.id AND x.status = 'completed') AS last_run_id,
           (SELECT x.asr_model FROM session_analysis_runs x
             WHERE x.session_id = s.id AND x.status = 'completed'
             ORDER BY x.id DESC LIMIT 1) AS last_asr_model
    FROM sessions s
    JOIN recordings r ON r.session_id = s.id AND r.deleted_at IS NULL
    ORDER BY s.id
    """
)

# Distribusi model di seluruh transkrip: peringatan dini dataset tercampur.
# `source` ikut dipisah supaya transkrip manual tidak tertukar dengan transkrip
# ASR lama yang belum punya kolom provenance.
_MODEL_MIX = text(
    """
    SELECT source,
           COALESCE(asr_model, '(tidak tercatat)') AS model,
           COUNT(*) AS n
    FROM transcripts
    GROUP BY source, asr_model
    ORDER BY source, n DESC
    """
)

_INSERT_RUN = text(
    """
    INSERT INTO session_analysis_runs
        (session_id, status, requested_steps, asr_model, llm_model, started_at, created_by)
    VALUES
        (:session_id, 'running', :steps, :asr_model, :llm_model, NOW(), :created_by)
    """
)

_RESULT = text(
    """
    SELECT r.status, r.error_code,
           m.speech_duration_ms, m.phonation_ms, m.silent_pause_count,
           m.syllable_count, m.word_count, m.filled_pause_total_ms,
           m.speech_rate, m.articulation_rate, m.quality_flag,
           (SELECT COUNT(*) FROM session_iu_suggestions s WHERE s.run_id = r.id) AS n_iu
    FROM session_analysis_runs r
    LEFT JOIN session_speech_metrics m ON m.run_id = r.id
    WHERE r.id = :run_id
    """
)


async def load_targets(only: set[int] | None) -> list[dict]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(_TARGETS)).mappings().all()
        mix = (await db.execute(_MODEL_MIX)).mappings().all()
    print("## Transkrip yang sudah ada\n")
    for m in mix:
        print(f"  - {m['source']:>6} / {m['model']}: {m['n']}")
    print(f"\nModel ASR aktif: {settings.ASR_MODEL} "
          f"({settings.ASR_DEVICE}/{settings.ASR_COMPUTE_TYPE}, "
          f"word_timestamps={settings.ASR_WORD_TIMESTAMPS})\n")
    if any(m["source"] == "asr" and m["model"] not in ("(tidak tercatat)", settings.ASR_MODEL) for m in mix):
        print("  PERINGATAN: sudah ada transkrip ASR dari model lain. "
              "Setelah rebuild, saring dengan asr_model sebelum menganalisis.\n")
    targets = [dict(r) for r in rows]
    if only is not None:
        targets = [t for t in targets if t["session_id"] in only]
    return targets


async def run_one(target: dict, steps: AnalysisRunIn, force: bool) -> int | None:
    session_id = target["session_id"]
    if not force and target["last_asr_model"] == settings.ASR_MODEL:
        print(f"  sesi {session_id}: dilewati (run {target['last_run_id']} "
              f"sudah memakai {settings.ASR_MODEL})")
        return None
    async with AsyncSessionLocal() as db:
        creator = (await db.execute(text("SELECT id FROM users ORDER BY id LIMIT 1"))).scalar()
        if creator is None:
            raise SystemExit("Tidak ada user di database; jalankan seed dulu.")
        result = await db.execute(
            _INSERT_RUN,
            {
                "session_id": session_id,
                "steps": steps.model_dump_json(),
                "asr_model": settings.ASR_MODEL,
                "llm_model": settings.AI_MODEL or None,
                "created_by": creator,
            },
        )
        run_id = result.lastrowid
        await db.commit()
    return run_id


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sessions", default=None, help="batasi ke id sesi tertentu, mis. 26,27,28")
    parser.add_argument("--dry-run", action="store_true", help="hanya tampilkan rencana, tidak menjalankan")
    parser.add_argument("--force", action="store_true", help="proses ulang walau modelnya sudah sama")
    parser.add_argument("--no-transcription", action="store_true", help="lewati ASR (pakai transkrip terakhir)")
    parser.add_argument("--no-iu", action="store_true", help="lewati saran IU (tanpa panggilan LLM)")
    args = parser.parse_args()

    only = {int(x) for x in args.sessions.split(",")} if args.sessions else None
    steps = AnalysisRunIn(
        run_transcription=not args.no_transcription,
        run_speech_metrics=True,
        run_iu_suggestions=not args.no_iu,
    )

    targets = await load_targets(only)
    if not targets:
        print("Tidak ada sesi dengan rekaman aktif.")
        return

    todo = [
        t for t in targets
        if args.force or t["last_asr_model"] != settings.ASR_MODEL
    ]
    print(f"Sesi dengan rekaman: {len(targets)} | akan diproses: {len(todo)}\n")
    if args.dry_run:
        for t in targets:
            mark = "PROSES" if t in todo else "lewati"
            print(f"  [{mark:6}] sesi {t['session_id']:>3}  status={t['session_status']}  "
                  f"run_terakhir={t['last_run_id']}  model={t['last_asr_model']}")
        print("\n(--dry-run: tidak ada yang dijalankan)")
        return

    started = time.time()
    run_ids: list[tuple[int, int]] = []
    for target in todo:
        session_id = target["session_id"]
        print(f"  sesi {session_id}: menjalankan…", flush=True)
        run_id = await run_one(target, steps, force=args.force)
        if run_id is None:
            continue
        t0 = time.time()
        # Reuse the exact production path, so a rebuild cannot drift from a
        # run triggered through the API.
        await _execute_run(run_id, session_id, steps)
        run_ids.append((session_id, run_id))
        print(f"  sesi {session_id}: run {run_id} selesai dalam {time.time() - t0:.1f}s", flush=True)

    print(f"\n## Hasil\n")
    print("| sesi | run | status | error | bicara ms | fonasi ms | jeda | suku | kata | filled ms | speech rate | artic rate | IU | flag |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    async with AsyncSessionLocal() as db:
        for session_id, run_id in run_ids:
            r = (await db.execute(_RESULT, {"run_id": run_id})).mappings().one()
            print(
                f"| {session_id} | {run_id} | {r['status']} | {r['error_code'] or '—'} | "
                f"{r['speech_duration_ms'] if r['speech_duration_ms'] is not None else '—'} | "
                f"{r['phonation_ms'] if r['phonation_ms'] is not None else '—'} | "
                f"{r['silent_pause_count'] if r['silent_pause_count'] is not None else '—'} | "
                f"{r['syllable_count'] if r['syllable_count'] is not None else '—'} | "
                f"{r['word_count'] if r['word_count'] is not None else '—'} | "
                f"{r['filled_pause_total_ms'] if r['filled_pause_total_ms'] is not None else '—'} | "
                f"{r['speech_rate'] if r['speech_rate'] is not None else '—'} | "
                f"{r['articulation_rate'] if r['articulation_rate'] is not None else '—'} | "
                f"{r['n_iu']} | {r['quality_flag'] or '—'} |"
            )
    print(f"\nSelesai: {len(run_ids)} run dalam {time.time() - started:.1f}s.")


asyncio.run(main())
