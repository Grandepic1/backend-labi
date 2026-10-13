from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Users
from app.schemas.token import Token
from app.schemas.user import LoginRequest, UserCreate, UserRead

router = APIRouter(prefix="/auth")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)) -> Users:
    role = (data.role or "caregiver").strip().lower()
    if role not in ("caregiver", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="role must be 'caregiver' or 'admin'",
        )
    existing = (
        await db.execute(
            select(Users).where(
                or_(Users.username == data.username, Users.email == str(data.email))
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        )
    user = Users(
        username=data.username,
        email=str(data.email),
        password=hash_password(data.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> Token:
    # JSON login with email + password.
    email = str(data.email).strip()
    user = (
        await db.execute(select(Users).where(Users.email == email))
    ).scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserRead)
async def read_me(current_user: Users = Depends(get_current_user)) -> Users:
    return current_user
