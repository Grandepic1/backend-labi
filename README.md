# backend-labi

FastAPI + SQLAlchemy **async** (MySQL via asyncmy) + Alembic (sync via pymysql).

## Setup

```powershell
uv sync
```

Copy `.env.example` to `.env` and adjust DB settings (or set `DATABASE_URL`).

## Run

```powershell
uv run uvicorn app.main:app --reload
# or
uv run python main.py
```

Health: `GET /api/v1/health`

## Alembic

```powershell
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
uv run alembic check
```

Models live in `app/models/` (import them in `app/models/__init__.py` so autogenerate sees them).
`alembic/env.py` reads the DB URL from `app.core.config.settings` (`.env` / `DATABASE_URL`).
