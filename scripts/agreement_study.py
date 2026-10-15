"""Studi kesepakatan AI vs manusia untuk penilaian Information Unit.

Membaca saran IU dari run analisis terakhir yang berstatus completed dan
assessment final dari pendamping, lalu melaporkan tingkat kesepakatannya.
Hanya sesi yang punya keduanya yang dihitung.

Pemakaian:
    .venv/Scripts/python.exe scripts/agreement_study.py
    .venv/Scripts/python.exe scripts/agreement_study.py --run-id 55
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The report is markdown and is meant to be redirected to a file; the SQL echo
# that helps while debugging the API would interleave with it. The OS
# environment outranks .env in pydantic-settings, so this is process-scoped.
os.environ.setdefault("DEBUG", "False")

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402

STATUSES = ("met", "not_met", "unclear")

_FINALS = text(
    """
    SELECT a.session_id AS session_id, a.id AS assessment_id
    FROM session_assessments a
    WHERE a.status = 'final'
    ORDER BY a.session_id
    """
)

_HUMAN_ITEMS = text(
    """
    SELECT ai.iu_id AS iu_id, iu.code AS code, iu.display_order AS display_order, ai.status AS status
    FROM session_assessment_items ai
    JOIN story_information_units iu ON iu.id = ai.iu_id
    WHERE ai.assessment_id = :assessment_id
    ORDER BY iu.display_order
    """
)

_LATEST_RUN = text(
    """
    SELECT MAX(s.run_id) AS run_id
    FROM session_iu_suggestions s
    JOIN session_analysis_runs r ON r.id = s.run_id
    WHERE s.session_id = :session_id AND r.status = 'completed'
    """
)

_AI_ITEMS = text(
    """
    SELECT iu_id, suggested_status AS status, evidence_quote AS quote
    FROM session_iu_suggestions
    WHERE run_id = :run_id
    """
)


async def collect(run_id: int | None) -> list[dict]:
    rows: list[dict] = []
    async with AsyncSessionLocal() as db:
        finals = (await db.execute(_FINALS)).mappings().all()
        for final in finals:
            if run_id is None:
                found = (await db.execute(_LATEST_RUN, {"session_id": final["session_id"]})).mappings().one()
                use_run = found["run_id"]
            else:
                use_run = run_id
            if use_run is None:
                continue
            human = (await db.execute(_HUMAN_ITEMS, {"assessment_id": final["assessment_id"]})).mappings().all()
            ai = {
                r["iu_id"]: r
                for r in (await db.execute(_AI_ITEMS, {"run_id": use_run})).mappings().all()
            }
            for item in human:
                suggestion = ai.get(item["iu_id"])
                rows.append(
                    {
                        "session_id": final["session_id"],
                        "run_id": use_run,
                        "code": item["code"],
                        "human_status": item["status"],
                        "ai_status": suggestion["status"] if suggestion else None,
                        "ai_quote": suggestion["quote"] if suggestion else None,
                    }
                )
    return rows


def report(rows: list[dict]) -> str:
    out: list[str] = []
    scored = [r for r in rows if r["ai_status"] is not None]
    total = len(scored)
    agree = sum(1 for r in scored if r["ai_status"] == r["human_status"])
    abstained = sum(1 for r in scored if r["ai_status"] == "unclear")
    decidable = [r for r in scored if r["ai_status"] in ("met", "not_met")]
    binary_agree = sum(1 for r in decidable if r["ai_status"] == r["human_status"])

    out.append("## Ringkasan\n")
    out.append(f"- Item IU yang dinilai AI: **{total}**")
    if total:
        out.append(f"- Sepakat persis (status sama): **{agree}/{total} = {agree / total * 100:.1f}%**")
        out.append(f"- AI abstain (`unclear`): **{abstained}/{total} = {abstained / total * 100:.1f}%**")
    if decidable:
        out.append(
            f"- Setelah abstain dikeluarkan: **{binary_agree}/{len(decidable)}"
            f" = {binary_agree / len(decidable) * 100:.1f}%**"
        )

    out.append("\n## Matriks manusia x AI\n")
    out.append("| manusia \\ AI | " + " | ".join(STATUSES) + " | total |")
    out.append("|---|---|---|---|---|")
    for human in STATUSES:
        cells = []
        for ai in STATUSES:
            n = sum(1 for r in scored if r["human_status"] == human and r["ai_status"] == ai)
            cells.append(str(n) if n else "·")
        out.append(f"| **{human}** | " + " | ".join(cells) + f" | {sum(1 for r in scored if r['human_status'] == human)} |")

    out.append("\n## Per sesi\n")
    out.append("| sesi | run | item | sepakat | abstain AI | tidak sepakat |")
    out.append("|---|---|---|---|---|---|")
    by_session: dict[int, list[dict]] = {}
    for row in scored:
        by_session.setdefault(row["session_id"], []).append(row)
    for sid in sorted(by_session):
        group = by_session[sid]
        ok = sum(1 for r in group if r["ai_status"] == r["human_status"])
        ab = sum(1 for r in group if r["ai_status"] == "unclear")
        bad = [r["code"] for r in group if r["ai_status"] != r["human_status"]]
        out.append(
            f"| {sid} | {group[0]['run_id']} | {len(group)} | {ok} ({ok / len(group) * 100:.0f}%) | {ab} | "
            f"{', '.join(bad) if bad else '—'} |"
        )

    mismatches = [r for r in scored if r["ai_status"] != r["human_status"]]
    if mismatches:
        out.append("\n## Rincian ketidaksepakatan\n")
        for r in mismatches:
            out.append(
                f"- **Sesi {r['session_id']} · {r['code']}** — manusia `{r['human_status']}`, "
                f"AI `{r['ai_status']}`, kutipan: `{r['ai_quote']}`"
            )
        reasons = Counter("abstain (unclear)" if r["ai_status"] == "unclear" else "salah nilai" for r in mismatches)
        out.append("\nPenyebab: " + ", ".join(f"{k} = {v}" for k, v in reasons.items()) + ".")

    unscored = [r for r in rows if r["ai_status"] is None]
    if unscored:
        out.append(f"\nCatatan: {len(unscored)} item tidak punya saran AI pada run ini.")

    return "\n".join(out)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, default=None, help="batasi ke satu run_id")
    args = parser.parse_args()

    rows = await collect(args.run_id)
    if not rows:
        print("Tidak ada sesi dengan assessment final + saran IU. Tidak ada yang bisa dilaporkan.")
        return
    print("# Studi kesepakatan AI vs manusia\n")
    print(f"Model penilai: `{settings.AI_MODEL}`\n")
    print(report(rows))


asyncio.run(main())
