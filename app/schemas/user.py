from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=8, max_length=72)
    # Labi role. Defaults to caregiver; pass "admin" to bootstrap
    # an admin account in MVP/demo environments.
    role: str = Field(default="caregiver", max_length=20)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str = "caregiver"
    created_at: datetime
    updated_at: datetime
