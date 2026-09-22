"""Phase 8: JWT authentication for the client connection.

Mirrors how the rest of the platform is expected to authenticate: a token
issued at login, verified here before a caller is allowed to open a pipeline
session. Standalone, this module owns issuing tokens too (see
scripts/issue_dev_token.py); in the full platform, issuance belongs to the
existing login endpoint and this module only verifies.
"""

import time

import jwt

from voicedesk_voice.config import JWT_ALGORITHM, JWT_EXPIRY_SECS, JWT_SECRET, REQUIRE_AUTH


class AuthError(Exception):
    """Raised when a connection can't be authenticated."""


def issue_token(subject: str, *, expiry_secs: int = JWT_EXPIRY_SECS) -> str:
    """Issue a signed token for ``subject`` (a user or caller id).

    Raises:
        AuthError: If JWT_SECRET isn't configured.
    """
    if not JWT_SECRET:
        raise AuthError("JWT_SECRET is not configured")

    now = int(time.time())
    claims = {"sub": subject, "iat": now, "exp": now + expiry_secs}
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str | None) -> dict:
    """Verify a token and return its claims.

    Raises:
        AuthError: If the token is missing, malformed, expired, or has a bad
            signature.
    """
    if not token:
        raise AuthError("Missing auth token")
    if not JWT_SECRET:
        raise AuthError("JWT_SECRET is not configured")

    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Auth token expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Invalid auth token: {e}") from e


def authenticate_session(body: dict) -> str | None:
    """Authenticate an incoming /start request body.

    Returns the authenticated subject (or None when auth is disabled).

    Raises:
        AuthError: If REQUIRE_AUTH is set and the token is missing/invalid.
    """
    if not REQUIRE_AUTH:
        return None

    token = body.get("token") if isinstance(body, dict) else None
    claims = verify_token(token)
    return claims.get("sub")
