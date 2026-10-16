import asyncio
import shutil
from pathlib import Path
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

TABLES_TO_CLEAR = [
    "session_training_recommendations",
    "session_training_logs",
    "session_assessment_items",
    "session_assessments",
    "session_iu_suggestions",
    "session_silent_pauses",
    "session_speech_metrics",
    "session_analysis_runs",
    "transcripts",
    "recordings",
    "sessions",
    "participants",
    "audit_logs",
]

async def reset_db():
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        for table in TABLES_TO_CLEAR:
            await db.execute(text(f"TRUNCATE TABLE `{table}`;"))
            print(f"Truncated {table}")
        await db.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        await db.commit()

    # Clean storage/recordings
    storage_rec = Path("storage/recordings")
    if storage_rec.exists():
        for item in storage_rec.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print("Cleared storage/recordings.")

    print("Database reset complete.")

if __name__ == "__main__":
    asyncio.run(reset_db())
