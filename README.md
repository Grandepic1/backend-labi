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

## Labi MVP (IU Recall)

Adapted from `Labi_PRD_MVP_IU_Recall.md` to this repo (not from zero):

| PRD | This repo |
|---|---|
| Postgres + UUID | MySQL + Integer PKs (matches existing `users.id`) |
| `JSONB` / `TIMESTAMPTZ` | `JSON` / `DATETIME` |
| S3/GCS object storage | `STORAGE_DIR/recordings/` local private dir, authorized streaming only |
| `users` from elsewhere | Local `users` extended with `role` (`caregiver` default, `admin`) |
| Participants assumed | Minimal `POST/GET /participants` added |
| Error envelope `{error:{code,…}}` | FastAPI-native `{detail}`; domain blocks use `422` with `ASSESSMENT_INCOMPLETE` prefix |

Flow: `POST /participants` → `GET /stories` → `POST /sessions`
→ `POST /sessions/{id}/recording` (multipart `file`, optional `duration_ms`,
`recorded_at`, `transcript_text`) → `GET .../recording` (stream)
→ `PUT .../assessment` (draft, repeatable) → `POST .../complete`
→ `GET .../result` + `GET /sessions` (history). Transcripts:
`POST/GET .../transcript`. Admin: `POST /admin/stories`,
`PUT /admin/stories/{id}` (new draft version), `POST/PUT/DELETE
.../ius`, `POST .../publish` (needs ≥1 IU), `POST .../archive`.

```powershell
copy .env.example .env   # set DB_* + SECRET_KEY, tune STORAGE_DIR / MAX_UPLOAD_BYTES
uv run alembic upgrade head
uv run python scripts/seed_labi.py   # demo story "Perjalanan ke Pasar" (9 IUs)
```

Register a caregiver, or pass `"role":"admin"` once to bootstrap an admin.
Recordings stream only with a valid JWT of the owning caregiver (or admin);
`IU Recall (%) = met/total*100` is always recomputed backend-side.

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
curl -X POST localhost:9008/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{"username":"alice","email":"alice@example.com","password":"Secret123!"}'

# Login (username or email) -> {"access_token": "...", "token_type": "bearer"}
curl -X POST localhost:9008/api/v1/auth/login `
  -F "username=alice" -F "password=Secret123!"

# Me (pass the token)
curl localhost:9008/api/v1/auth/me -H "Authorization: Bearer <token>"
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

## Deploy (Linux: docker + nginx)

Files: `Dockerfile`, `docker-compose.yml`, `.dockerignore`,
`deploy/systemd/backend-labi.service` (optional thin wrapper),
`deploy/nginx/backend-labi.conf`. The container is the service layer
(`restart: unless-stopped`): source is bind-mounted so code changes need
only a restart, dependencies live in the image venv (`uv run` = venv python).

```bash
# Server .env must have: APP_ENV=production, a real SECRET_KEY,
# FRONTEND_URLS with your domain(s), and DB_HOST=host.docker.internal
# (MySQL runs on the docker host; 127.0.0.1 inside the container
# means the container itself).

# 1. App service (localhost-only :9008, auto-migrates on start)
docker compose up -d --build
docker compose restart api   # after code changes (no rebuild needed)
docker compose logs -f api

# Optional: manage it via systemd instead (boot order + systemctl status)
sudo cp deploy/systemd/backend-labi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now backend-labi

# 2. HTTPS + reverse proxy (replace api.example.com with your domain)
sudo cp deploy/nginx/backend-labi.conf /etc/nginx/sites-available/backend-labi
sudo ln -s /etc/nginx/sites-available/backend-labi /etc/nginx/sites-enabled/
sudo certbot --nginx -d api.example.com
sudo nginx -t && sudo systemctl reload nginx
```
