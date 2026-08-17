"""MongoDB storage for institution configs (ADR-0005, TASK-E05-1).

Storage-layer only: no HTTP routes (that's TASK-E05-3) and no upload/parsing logic (that's
TASK-E05-2). Documents live in the `institution_configs` collection, keyed by `institution_id`.

`update_accuracy_weight` (TASK-E09-2) is the first update path this module has: prior to it,
`accuracy_weight` was only ever set once, at config-creation time (see `formatting.seed` and
`formatting.discovery`), and never touched again.
"""

import re
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.formatting.models import InstitutionConfig

_COLLECTION = "institution_configs"


async def create_institution_config(
    db: AsyncIOMotorDatabase, config: InstitutionConfig
) -> InstitutionConfig:
    """Insert `config` into the `institution_configs` collection and return it unchanged.

    Raises whatever `motor`/pymongo raises on a duplicate `institution_id` if a unique index is
    later added; this function performs no uniqueness check of its own.
    """
    await db[_COLLECTION].insert_one(config.model_dump())
    return config


async def get_institution_config(
    db: AsyncIOMotorDatabase, institution_id: str
) -> InstitutionConfig | None:
    """Fetch the institution config with `institution_id`, or `None` if it doesn't exist."""
    document = await db[_COLLECTION].find_one({"institution_id": institution_id})
    if document is None:
        return None
    return InstitutionConfig.model_validate(document)


async def get_institution_config_by_name(
    db: AsyncIOMotorDatabase, institution_name: str
) -> InstitutionConfig | None:
    """Fetch a stored institution config by name (case-insensitive, ignoring surrounding
    whitespace), or `None` if none exists.

    Used by `formatting.router`'s upload/auto-detect endpoints to dedupe: repeating either flow
    for the same university name should reuse the one shared config instead of inserting a new,
    independently-drifting document every time (user report: repeated setup attempts for the same
    university produced many duplicate configs).
    """
    document = await db[_COLLECTION].find_one(
        {"institution_name": {"$regex": f"^{re.escape(institution_name.strip())}$", "$options": "i"}}
    )
    if document is None:
        return None
    return InstitutionConfig.model_validate(document)


async def list_institution_configs(db: AsyncIOMotorDatabase) -> list[InstitutionConfig]:
    """Return all stored institution configs, in no particular order."""
    cursor = db[_COLLECTION].find({})
    documents = await cursor.to_list(length=None)
    return [InstitutionConfig.model_validate(document) for document in documents]


async def update_accuracy_weight(
    db: AsyncIOMotorDatabase, institution_id: str, accuracy_weight: float
) -> InstitutionConfig | None:
    """Set `accuracy_weight` (and `updated_at`) on the stored config for `institution_id`.

    Returns the updated `InstitutionConfig`, or `None` if `institution_id` doesn't exist (mirrors
    `get_institution_config`'s miss-handling rather than raising). Callers are expected to compute
    `accuracy_weight` themselves (see `feedback.weights.recompute_accuracy_weight`); this function
    performs no validation of the value beyond persisting it as given.
    """
    result = await db[_COLLECTION].update_one(
        {"institution_id": institution_id},
        {"$set": {"accuracy_weight": accuracy_weight, "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count == 0:
        return None
    return await get_institution_config(db, institution_id)
