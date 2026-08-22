import pytest
from fastapi import HTTPException

from app.auth.jwt import create_token, decode_token
from app.auth.security import hash_password, verify_password
from app.config import Settings


def test_password_hash_does_not_expose_plaintext():
    password = "A long unique test password!"
    hashed = hash_password(password)
    assert password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password("wrong password", hashed)


def test_tokens_preserve_token_version():
    settings = Settings(JWT_SECRET="test-secret-key-for-pytest-only")
    token = create_token(settings, "00000000-0000-0000-0000-000000000001", "access", 4)
    assert decode_token(settings, token, "access")["ver"] == 4


def test_refresh_token_cannot_be_used_as_access_token():
    settings = Settings(JWT_SECRET="test-secret-key-for-pytest-only")
    token = create_token(settings, "00000000-0000-0000-0000-000000000001", "refresh")
    with pytest.raises(HTTPException):
        decode_token(settings, token, "access")
