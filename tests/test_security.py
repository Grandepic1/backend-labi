from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hashing() -> None:
    pw = "secret-pass-123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong-pass", hashed) is False


def test_jwt_token() -> None:
    user_id = "42"
    token = create_access_token(user_id)
    decoded = decode_access_token(token)
    assert decoded == user_id


def test_jwt_invalid_token() -> None:
    assert decode_access_token("invalid.token.signature") is None
