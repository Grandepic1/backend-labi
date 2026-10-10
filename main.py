import uvicorn

from app.core.config import settings
from app.main import app

__all__ = ["app"]


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug_mode,
    )


if __name__ == "__main__":
    main()
