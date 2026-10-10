from fastapi import FastAPI

from app.api.v1 import v1_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
