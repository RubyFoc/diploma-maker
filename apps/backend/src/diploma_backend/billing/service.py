"""Wallet auto-creation hook (TASK-E02-2). Schema/cost-logging only — see ADR-0007."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.billing.models import new_wallet_document


async def create_wallet_for_user(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    """Insert a zeroed Wallet document for `user_id` into the `wallets` collection.

    Called once at registration time (TASK-E02-1). Side effect: one insert into `wallets`.
    Output: the inserted Wallet document.
    """
    wallet = new_wallet_document(user_id)
    await db["wallets"].insert_one(wallet)
    return wallet
