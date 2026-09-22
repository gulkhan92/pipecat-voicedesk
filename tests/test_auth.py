"""Phase 9: unit tests for JWT authentication (Phase 8)."""

import time

import jwt
import pytest

from voicedesk_voice import auth


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")


def test_issue_and_verify_round_trip():
    token = auth.issue_token("user-123")
    claims = auth.verify_token(token)
    assert claims["sub"] == "user-123"


def test_verify_rejects_missing_token():
    with pytest.raises(auth.AuthError):
        auth.verify_token(None)


def test_verify_rejects_expired_token():
    expired = jwt.encode(
        {"sub": "user-123", "iat": int(time.time()) - 100, "exp": int(time.time()) - 1},
        "test-secret",
        algorithm="HS256",
    )
    with pytest.raises(auth.AuthError):
        auth.verify_token(expired)


def test_verify_rejects_bad_signature():
    token = jwt.encode(
        {"sub": "user-123", "iat": int(time.time()), "exp": int(time.time()) + 60},
        "a-different-secret",
        algorithm="HS256",
    )
    with pytest.raises(auth.AuthError):
        auth.verify_token(token)


def test_authenticate_session_skips_verification_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    assert auth.authenticate_session({}) is None


def test_authenticate_session_requires_valid_token_when_auth_enabled(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", True)

    with pytest.raises(auth.AuthError):
        auth.authenticate_session({})

    token = auth.issue_token("user-456")
    assert auth.authenticate_session({"token": token}) == "user-456"
