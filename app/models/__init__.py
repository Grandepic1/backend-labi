"""Register models here so Alembic autogenerate can see them."""

from app.core.database import Base
from app.models.Users import Users

__all__ = ["Base", "Users"]
