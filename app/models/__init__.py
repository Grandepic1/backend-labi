"""Register models here so Alembic autogenerate can see them."""

from app.core.database import Base  # noqa: F401

__all__ = ["Base"]
