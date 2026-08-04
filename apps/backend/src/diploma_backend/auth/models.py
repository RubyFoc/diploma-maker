"""User document shape and helpers (ADR-0006: `{id, email, password_hash, created_at}`)."""

import uuid
from datetime import UTC, datetime


def new_user_document(email: str, password_hash: str) -> dict:
    """Build a new User document.

    Inputs: `email` (already lowercase/normalized by the caller), `password_hash` (bcrypt hash,
    never the plaintext password). Output: a dict matching ADR-0006's User schema, with a fresh
    UUID `id` and `created_at` set to now (UTC).
    """
    return {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": password_hash,
        "created_at": datetime.now(UTC),
    }
