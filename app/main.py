import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import v1_router
from app.core.config import settings


def setup_logging() -> None:
    """INFO in development, WARNING in production (uvicorn + sqlalchemy)."""
    level = logging.WARNING if settings.is_production else logging.INFO
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(level)


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.debug_mode,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
