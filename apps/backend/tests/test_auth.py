"""Tests for TASK-E02-1 (register/login), TASK-E02-2 (wallet auto-creation), and TASK-E02-3
(JWT auth dependency), using the in-memory Mongo fake from `conftest.py`.
"""

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str = "student@example.com", password: str = "hunter22") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return response.json()


def test_register_creates_user_and_zeroed_wallet(client: TestClient) -> None:
    import asyncio

    from diploma_backend.db import get_database
    from diploma_backend.main import app

    body = _register(client)
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    fake_db = app.dependency_overrides[get_database]()

    async def _fetch() -> tuple[dict, dict]:
        user = await fake_db["users"].find_one({"email": "student@example.com"})
        wallet = await fake_db["wallets"].find_one({"user_id": user["id"]})
        return user, wallet

    user, wallet = asyncio.run(_fetch())
    assert user is not None
    assert user["password_hash"] != "hunter22"
    assert wallet is not None
    assert wallet["token_balance"] == 0
    assert wallet["free_pages_used_today"] == 0


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/auth/register", json={"email": "student@example.com", "password": "otherpass1"}
    )
    assert response.status_code == 409


def test_login_happy_path(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/auth/login", json={"email": "student@example.com", "password": "hunter22"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/auth/login", json={"email": "student@example.com", "password": "wrongpass1"}
    )
    assert response.status_code == 401


def test_protected_route_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_protected_route_rejects_invalid_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_protected_route_accepts_valid_token(client: TestClient) -> None:
    token = _register(client)["access_token"]
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert "user_id" in response.json()
