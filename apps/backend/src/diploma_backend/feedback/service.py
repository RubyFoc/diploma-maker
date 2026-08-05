"""MongoDB storage for feedback signals.

Storage-layer only: no HTTP routes (that's `feedback.router`) and no weight-adjustment logic
(that's TASK-E09-2, not implemented here). Documents live in one collection, `feedback_signals`,
keyed by `id` (see `feedback.models`).
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.feedback.models import FeedbackSignal, SignalType

_FEEDBACK_SIGNALS_COLLECTION = "feedback_signals"


async def record_signal(
    db: AsyncIOMotorDatabase,
    institution_id: str,
    chapter_id: str,
    version_id: str,
    signal_type: SignalType,
) -> FeedbackSignal:
    """Create and insert a new `FeedbackSignal` for the given draft/template combination.

    Deliberately does not validate that `institution_id`, `chapter_id`, or `version_id` refer to
    anything that still exists: this is an audit log of what the user did, and a signal
    referencing a since-deleted chapter is still a valid historical fact. This codebase has no
    chapter/institution deletion anyway, so cross-referencing here would just be unnecessary
    coupling to `projects`/`formatting`/`versions`.
    """
    signal = FeedbackSignal(
        institution_id=institution_id,
        chapter_id=chapter_id,
        version_id=version_id,
        signal_type=signal_type,
    )
    await db[_FEEDBACK_SIGNALS_COLLECTION].insert_one(signal.model_dump())
    return signal


async def list_signals_for_institution(
    db: AsyncIOMotorDatabase, institution_id: str
) -> list[FeedbackSignal]:
    """Return all feedback signals recorded for `institution_id`, ordered by `created_at`.

    This is the shape TASK-E09-2 will consume to compute `accuracy_weight` adjustments; that
    consumer is not implemented here — this function only makes the data queryable.
    """
    cursor = (
        db[_FEEDBACK_SIGNALS_COLLECTION]
        .find({"institution_id": institution_id})
        .sort("created_at", 1)
    )
    documents = await cursor.to_list(length=None)
    return [FeedbackSignal.model_validate(document) for document in documents]
