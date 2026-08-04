"""Registration/login endpoints and a JWT-protected sample route (TASK-E02-1, TASK-E02-3)."""

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.auth.models import new_user_document
from diploma_backend.auth.security import create_access_token, hash_password, verify_password
from diploma_backend.billing.service import create_wallet_for_user
from diploma_backend.db import get_database

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    """Request body shared by register/login: email + plaintext password."""

    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    """JWT issued on successful register/login."""

    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    credentials: Credentials, db: AsyncIOMotorDatabase = Depends(get_database)
) -> TokenResponse:
    """Create a User with a hashed password, auto-create its zeroed Wallet, and return a JWT.

    Raises `HTTPException(409)` if `credentials.email` is already registered.
    """
    existing = await db["users"].find_one({"email": credentials.email})
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = new_user_document(credentials.email, hash_password(credentials.password))
    await db["users"].insert_one(user)
    await create_wallet_for_user(db, user["id"])

    return TokenResponse(access_token=create_access_token(user["id"]))


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: Credentials, db: AsyncIOMotorDatabase = Depends(get_database)
) -> TokenResponse:
    """Authenticate by email/password and return a JWT.

    Raises `HTTPException(401)` if the email is unknown or the password doesn't match — the
    same error either way, so the response never reveals whether the email exists.
    """
    user = await db["users"].find_one({"email": credentials.email})
    if user is None or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    return TokenResponse(access_token=create_access_token(user["id"]))


@router.get("/me")
async def me(user_id: str = Depends(get_current_user_id)) -> dict[str, str]:
    """Protected sample route: returns the authenticated caller's user id (TASK-E02-3)."""
    return {"user_id": user_id}
