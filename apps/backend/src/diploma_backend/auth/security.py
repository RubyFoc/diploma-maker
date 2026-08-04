"""Password hashing and JWT issuance/verification helpers (TASK-E02-1, TASK-E02-3)."""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = 60 * 24


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt. Returns the hash as a str for storage."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash. Returns False on any mismatch."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _secret_key() -> str:
    """Read the JWT signing secret from `JWT_SECRET_KEY`. Never logged or printed."""
    return os.environ.get("JWT_SECRET_KEY", "change-me")


def create_access_token(user_id: str) -> str:
    """Issue a signed JWT carrying `user_id` as the `sub` claim, expiring after
    `JWT_EXPIRES_MINUTES`.
    """
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=JWT_EXPIRES_MINUTES)}
    return jwt.encode(payload, _secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Validate a JWT and return the user id (`sub` claim).

    Raises `jwt.PyJWTError` (or a subclass, e.g. `ExpiredSignatureError`,
    `InvalidSignatureError`) if the token is malformed, expired, or has an invalid signature.
    """
    payload = jwt.decode(token, _secret_key(), algorithms=[JWT_ALGORITHM])
    return payload["sub"]
