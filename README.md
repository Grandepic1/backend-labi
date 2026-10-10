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

## Environments (`APP_ENV`)

`APP_ENV=development` (default) vs `APP_ENV=production`:

| Behavior | development | production |
|---|---|---|
| `/docs`, `/redoc` | on | off (404) |
| Tracebacks / debug mode | per `DEBUG` | always off |
| SQL echo | per `DEBUG` | always off |
| Logs (uvicorn, sqlalchemy) | INFO | WARNING |
| Auto-reload (`python main.py`) | per `DEBUG` | always off |

## Frontend domains (CORS)

List your frontend URLs in `.env` (comma-separated):

```env
FRONTEND_URLS=http://localhost:3000,https://app.example.com
```

Only these origins can call the API from a browser.

## Auth (JWT)

```powershell
# Register
curl -X POST localhost:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{"username":"alice","email":"alice@example.com","password":"Secret123!"}'

# Login (username or email) -> {"access_token": "...", "token_type": "bearer"}
curl -X POST localhost:8000/api/v1/auth/login `
  -F "username=alice" -F "password=Secret123!"

# Me (pass the token)
curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer <token>"
```

Set a real `SECRET_KEY` in `.env` for production. Protect routes with
`Depends(get_current_user)` from `app.api.deps`.

## Alembic

```powershell
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
uv run alembic check
```

Models live in `app/models/` (import them in `app/models/__init__.py` so autogenerate sees them).
`alembic/env.py` reads the DB URL from `app.core.config.settings` (`.env` / `DATABASE_URL`).
