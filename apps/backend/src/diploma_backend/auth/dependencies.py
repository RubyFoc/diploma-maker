"""FastAPI dependency enforcing Bearer JWT auth on protected routes (TASK-E02-3)."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from diploma_backend.auth.security import decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Extract and validate the user id from the request's `Authorization: Bearer <jwt>` header.

    Output: the `sub` claim (user id) of a valid token.
    Raises `HTTPException(401)` if the header is missing, not a Bearer token, or the token is
    invalid/expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    try:
        return decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc
