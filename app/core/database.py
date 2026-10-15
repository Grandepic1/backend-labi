from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def pin_connection_to_utc(dbapi_connection, connection_record) -> None:
    """Paksa setiap koneksi database bekerja dalam UTC.

    Server MySQL berjalan pada waktu lokal (`SE Asia Standard Time`, UTC+7).
    Akibatnya `server_default=func.now()` menyimpan waktu lokal, sementara
    aplikasi menulis UTC dari Python (`datetime.now(timezone.utc)`), sehingga
    satu tabel memuat dua jam yang berbeda tujuh jam. Contohnya sesi 26:
    `recordings.created_at` = 2026-10-14 00:07:32 (lokal) sedangkan
    `sessions.completed_at` = 2026-10-13 17:26:53 (UTC).

    Menyetel zona sesi membuat `NOW()` dan `CURRENT_TIMESTAMP` sejalan dengan
    Python. Semua kolom bertipe `DATETIME`, bukan `TIMESTAMP`, jadi ini hanya
    mengubah nilai *default* untuk baris baru; nilai yang sudah tersimpan tidak
    tersentuh dan konversi baris lama dikerjakan migrasi
    `c3f81d5a6b24_normalize_timestamps_to_utc`.

    Dipakai bersama oleh engine async aplikasi dan engine sinkron Alembic.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET time_zone = '+00:00'")
    finally:
        cursor.close()


engine = create_async_engine(
    settings.sqlalchemy_async_url,
    pool_pre_ping=True,
    echo=settings.sql_echo,
)

event.listens_for(engine.sync_engine, "connect")(pin_connection_to_utc)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
