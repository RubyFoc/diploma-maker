"""MongoDB storage for institution configs (ADR-0005, TASK-E05-1).

Storage-layer only: no HTTP routes (that's TASK-E05-3) and no upload/parsing logic (that's
TASK-E05-2). Documents live in the `institution_configs` collection, keyed by `institution_id`.
"""

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


async def list_institution_configs(db: AsyncIOMotorDatabase) -> list[InstitutionConfig]:
    """Return all stored institution configs, in no particular order."""
    cursor = db[_COLLECTION].find({})
    documents = await cursor.to_list(length=None)
    return [InstitutionConfig.model_validate(document) for document in documents]
