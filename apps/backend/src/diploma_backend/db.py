"""MongoDB connection management for the diploma-maker backend.

Provides a lazily-created `motor` client and a FastAPI dependency (`get_database`) that
request handlers use to reach collections. Tests override `get_database` via
`app.dependency_overrides` with an in-memory fake (`mongomock-motor`) instead of touching a
real MongoDB instance.
"""

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    """Return the process-wide MongoDB client, creating it from `MONGODB_URI` on first use."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency yielding the application's MongoDB database handle."""
    return get_client()[os.environ.get("MONGODB_DB_NAME", "diploma_maker")]
