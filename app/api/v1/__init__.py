from fastapi import APIRouter

from app.api.v1.routes.admin_stories import router as admin_stories_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.participants import router as participants_router
from app.api.v1.routes.sessions import router as sessions_router
from app.api.v1.routes.stories import router as stories_router

v1_router = APIRouter()
v1_router.include_router(health_router, tags=["health"])
v1_router.include_router(auth_router, tags=["auth"])
v1_router.include_router(participants_router)
v1_router.include_router(stories_router)
v1_router.include_router(sessions_router)
v1_router.include_router(admin_stories_router)
