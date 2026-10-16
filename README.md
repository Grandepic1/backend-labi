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

## Labi analysis (automatic IU suggestions + CSAP voice metrics)

Everything runs locally: `faster-whisper` in-process for ASR, LM Studio's
OpenAI-compatible server for the IU suggestions, `ffmpeg` for pause detection.
Local inference takes tens of seconds to minutes, so the analysis is a
background run with polling (one uvicorn worker — the run is in-process).

```powershell
ffmpeg -version                            # ffmpeg + ffprobe must be on PATH
uv run python scripts/fetch_asr_model.py   # downloads the ASR weights into ./models (once)
```

Flow, continuing after the recording upload:

| Step | Call |
|---|---|
| Queue the run → `202` + `run_id` | `POST /sessions/{id}/analysis`, body `{"run_transcription":true,"run_speech_metrics":true,"run_iu_suggestions":true}` (all default `true`, so a bare `{}` runs everything) |
| Poll | `GET /sessions/{id}/analysis` → `status` (`running\|completed\|failed`), `error_code`, `speech_metrics`, `iu_suggestions`, `transcript_source` |
| Seed the draft assessment from the suggestions | `POST /sessions/{id}/assessment/from-suggestions` → `200` draft (the model never finalizes; `unclear` still blocks `/complete`) |
| Compare sessions over time | `GET /participants/{id}/analysis-trend` → `series`, `baseline`, `latest`, `deltas` |

The `run_transcription` step appends a `transcripts` row with `source="asr"`
(never overwrites), which `GET .../transcript` then returns. Metrics are CSAP
table 2 items 1-10 derived from the audio — silent-pause count/total/mean/median/sd,
speech rate, articulation rate, pause rate per 100 words — plus the
syllable/word/filled-pause counts they rest on; items 11-19 need
syntactic/prosodic annotation and are deliberately not computed. Every detected
pause is stored raw (`start_ms`/`end_ms`) and the raw transcript is kept, so
thresholds and counts can be re-derived without re-running ffmpeg or ASR.

`.env` keys: `FFMPEG_BIN`, `FFPROBE_BIN`, `FFMPEG_TIMEOUT_SECONDS`,
`PAUSE_NOISE_DB`, `PAUSE_MIN_MS`, `FILLED_PAUSE_TOKENS`, `AI_BASE_URL`,
`AI_API_KEY`, `AI_MODEL`, `AI_TIMEOUT_SECONDS`, `ASR_MODEL`, `ASR_DEVICE`,
`ASR_COMPUTE_TYPE`, `ASR_MODEL_DIR`, `ASR_LANGUAGE`, `ASR_BEAM_SIZE`,
`ASR_VAD_FILTER`, `ASR_TIMEOUT_SECONDS`. Read the model id from
`GET {AI_BASE_URL}/models`; with `AI_MODEL` empty the IU step fails with
`AI_NOT_CONFIGURED` (visible through the `GET`). `ASR_DEVICE=cpu` with
`ASR_COMPUTE_TYPE=int8` is the safe default; on a machine with the full CUDA
runtime use `cuda` + `float16`.

A failed run reports one of `AI_NOT_CONFIGURED`, `AI_REQUEST_FAILED`,
`AI_INVALID_OUTPUT`, `ASR_MODEL_UNAVAILABLE`, `ASR_TIMEOUT`, `ASR_FAILED`,
`FFMPEG_MISSING`, `FFMPEG_FAILED`, `NO_TRANSCRIPT`, `INTERNAL` in `error_code`;
artifacts committed by earlier steps (e.g. metrics before a failed IU step)
stay readable.

In Docker, ffmpeg is installed in the image, `./models` is shared with the
container through the existing bind mount (download the weights once on the
host), and LM Studio on the host needs
`AI_BASE_URL=http://host.docker.internal:1234/v1` in `.env`.

Remote ASR (weak server CPU): run `../transcribe-model` on the GPU box
(`uv run python main.py` → `0.0.0.0:8001`), then set
`ASR_REMOTE_URL=http://10.66.66.X:8001` (+ `ASR_REMOTE_API_KEY`) in the
server `.env`. Transcription then goes over HTTP to the GPU box with the OG
decode params (`ASR_MODEL`/`ASR_LANGUAGE`/`ASR_BEAM_SIZE`/`ASR_VAD_FILTER`
sent per request); empty `ASR_REMOTE_URL` keeps the OG in-process behavior.
Only the ASR step moves — `ffmpeg` metrics and the LLM step stay local.

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

# Login (email + password JSON) -> {"access_token": "...", "token_type": "bearer"}
curl -X POST localhost:9008/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"alice@example.com","password":"Secret123!"}'

# Me (pass the token)
curl localhost:9008/api/v1/auth/me -H "Authorization: Bearer <token>"
```

Set a real `SECRET_KEY` in `.env` for production. Protect routes with
`Depends(get_current_user)` from `app.api.deps`.

## Survivor personalization (onboarding)

The app runs a personalization step right after login, where the companion
(pendamping) fills in a profile for the survivor (penyintas) they accompany. It
is a singleton per account: a companion accompanies exactly one survivor, so the
profile lives in `survivor_profiles` with a unique `user_id`. That is also what
tells the app whether onboarding is done — `GET` returns `404` until a profile
exists.

```powershell
# Get my survivor profile (404 before onboarding)
curl localhost:9008/api/v1/me/survivor-profile -H "Authorization: Bearer <token>"

# Create or replace it (idempotent — safe to re-submit onboarding)
curl -X PUT localhost:9008/api/v1/me/survivor-profile `
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" `
  -d '{`
    "name": "Bu Siti",`
    "age_range": "70-79",`
    "primary_language": "jv",`
    "communication_goals": ["everyday_storytelling", "answering_questions"],`
    "instruction_preference": "short_simple",`
    "preferred_session_duration": "5",`
    "preferred_topics": ["family", "food"],`
    "practice_mode": "companion",`
    "personalization_confirmed": true`
  }'

# Remove it (runs personalization again)
curl -X DELETE localhost:9008/api/v1/me/survivor-profile -H "Authorization: Bearer <token>"
```

`name` is the survivor's nickname (required, 1-50 chars). Every other field is
optional and accepts only the values the app offers during personalization; see
`app/schemas/survivor_profile.py` for the exact enums. `communication_goals` and
`preferred_topics` are lists stored as JSON and are deduplicated.

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
# FRONTEND_URLS with your domain(s), and DB_HOST=127.0.0.1 (host-side MySQL;
# docker-compose overrides it to host.docker.internal inside the container).

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
