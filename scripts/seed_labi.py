import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Story, StoryInformationUnit, StoryVersion

SLUG = "perjalanan-ke-pasar"

STORY_TEXT = (
    "Pada hari Minggu, Ibu pergi ke pasar bersama anak perempuannya. "
    "Di sana Ibu membeli dua buah apel seharga lima ribu rupiah. "
    "Dalam perjalanan pulang hujan turun, sehingga mereka berteduh di warung. "
    "Mereka sampai di rumah pada sore hari."
)

INSTRUCTIONS = (
    "Bacakan cerita satu kali dengan tempo wajar. "
    "Minta peserta menceritakan kembali tanpa melihat teks."
)

IUS = [
    ("IU1", "Menyebut hari Minggu", "Diberi skor met jika hari disebut sebagai Minggu",
     ["hari Minggu", "Minggu"], 1),
    ("IU2", "Menyebut Ibu sebagai pelaku", "Diberi skor met jika Ibu disebut sebagai pelaku utama",
     ["Ibu", "ibunya"], 2),
    ("IU3", "Menyebut pergi ke pasar", "Diberi skor met jika tujuan ke pasar disebutkan",
     ["pasar", "ke pasar"], 3),
    ("IU4", "Menyebut bersama anak perempuan", "Diberi skor met jika teman pergi (anak perempuan) disebutkan",
     ["anak perempuan", "putrinya", "anaknya"], 4),
    ("IU5", "Menyebut membeli dua buah apel", "Diberi skor met jika barang (apel) dan jumlah (dua) disebutkan",
     ["dua apel", "2 apel", "membeli apel"], 5),
    ("IU6", "Menyebut harga lima ribu rupiah", "Diberi skor met jika harga lima ribu disebutkan",
     ["lima ribu", "5000", "Rp5.000"], 6),
    ("IU7", "Menyebut hujan turun saat pulang", "Diberi skor met jika hujan dalam perjalanan pulang disebutkan",
     ["hujan", "hujan turun"], 7),
    ("IU8", "Menyebut berteduh di warung", "Diberi skor met jika berteduh di warung disebutkan",
     ["berteduh", "warung", "teduh di warung"], 8),
    ("IU9", "Menyebut sampai rumah sore hari", "Diberi skor met jika tiba di rumah sore hari disebutkan",
     ["sore hari", "sampai rumah", "tiba di rumah"], 9),
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        story = (await db.execute(select(Story).where(Story.slug == SLUG))).scalar_one_or_none()
        if story is None:
            story = Story(slug=SLUG, status="published")
            db.add(story)
            await db.flush()
            version = StoryVersion(
                story_id=story.id,
                version_number=1,
                title="Perjalanan ke Pasar",
                story_text=STORY_TEXT,
                instructions=INSTRUCTIONS,
                language="id",
                estimated_duration_seconds=45,
                status="published",
            )
            db.add(version)
            await db.flush()
            for code, desc, rule, variants, order in IUS:
                db.add(StoryInformationUnit(
                    story_version_id=version.id,
                    code=code,
                    description=desc,
                    scoring_rule=rule,
                    accepted_variants=variants,
                    display_order=order,
                    is_active=True,
                ))
            await db.commit()
            print(f"seeded story '{SLUG}' v1 with {len(IUS)} IUs")
        else:
            print(f"story '{SLUG}' already exists (id={story.id}), skipping")


if __name__ == "__main__":
    asyncio.run(main())
