from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import Users

bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Users:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    subject = decode_access_token(credentials.credentials)
    if subject is None:
        raise credentials_exception
    try:
        user_id = int(subject)
    except ValueError:
        raise credentials_exception
    user = (
        await db.execute(select(Users).where(Users.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


def require_admin(current_user: Users = Depends(get_current_user)) -> Users:
    if (current_user.role or "caregiver") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def is_admin(user: Users) -> bool:
    return (user.role or "caregiver") == "admin"
