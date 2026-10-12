import uvicorn

from app.core.config import settings
from app.main import app

__all__ = ["app"]


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=9008,
        reload=settings.debug_mode,
    )


if __name__ == "__main__":
    main()
