from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# bcrypt refuses passwords longer than 72 *bytes* (not characters).
BCRYPT_MAX_PASSWORD_BYTES = 72


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=8, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    # Labi role. Defaults to caregiver; pass "admin" to bootstrap
    # an admin account in MVP/demo environments.
    role: str = Field(default="caregiver", max_length=20)

    @field_validator("password")
    @classmethod
    def _password_within_bcrypt_limit(cls, value: str) -> str:
        """Reject passwords that encode to more than 72 bytes.

        max_length counts characters, so a short password of multibyte
        characters (e.g. emoji or CJK) can still exceed bcrypt's 72-byte
        limit and make hashing raise.
        """
        if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                f"password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes "
                "when UTF-8 encoded"
            )
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str = "caregiver"
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=1, max_length=BCRYPT_MAX_PASSWORD_BYTES)
