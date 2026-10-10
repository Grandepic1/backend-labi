# backend-labi — service runtime image.
#
# No application source is baked in (no `COPY . .`): dependencies are
# installed into a venv at /opt/venv via uv, and the source is bind-mounted
# by docker-compose.yml. Code updates need only `docker compose restart api`.
# Everything runs on the venv python through `uv run`.

FROM python:3.13-slim

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Manifests only — cached layer, rebuilt only when dependencies change.
COPY pyproject.toml uv.lock README.md ./

RUN uv sync --frozen --no-dev

EXPOSE 9008

# On every (re)start: sync deps (no-op if unchanged), apply migrations,
# then serve. If MySQL isn't reachable yet the container exits and the
# compose restart policy brings it back until the DB is up.
CMD ["sh", "-c", "uv sync --frozen --no-dev --quiet && uv run alembic upgrade head && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 9008 --proxy-headers --forwarded-allow-ips='*'"]
