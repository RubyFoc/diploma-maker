"""Feedback signal capture endpoint (TASK-E09-1, TASK-E09-2).

Composes `feedback.service` (signal storage) and `feedback.weights` (accuracy-weight recompute)
without modifying either's internals. `POST /feedback/signals` records the raw signal and then,
in the same request, recomputes and persists the signal's institution's
`InstitutionConfig.accuracy_weight` from its full signal history (`feedback.weights`) — this is
what makes E09's "visible on the next generation for that template" property hold, since any
`formatting`-config read after this call sees the freshly recomputed weight. The recompute is a
cheap Mongo read+write (no LLM call), so it runs synchronously and is allowed to raise like any
other part of this endpoint, unlike the fire-and-forget humanizer/plagiarism side effects
elsewhere in this codebase.
"""

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.db import get_database
from diploma_backend.feedback.models import FeedbackSignal, SignalType
from diploma_backend.feedback.service import record_signal
from diploma_backend.feedback.weights import recompute_accuracy_weight

router = APIRouter(prefix="/feedback", tags=["feedback"])


class RecordSignalRequest(BaseModel):
    """Body for `POST /feedback/signals`."""

    institution_id: str
    chapter_id: str
    version_id: str
    signal_type: SignalType


@router.post("/signals", response_model=FeedbackSignal, status_code=status.HTTP_201_CREATED)
async def record_signal_endpoint(
    body: RecordSignalRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> FeedbackSignal:
    """Record that a user approved, rejected, or edited a chapter draft.

    Deliberately does not check that `institution_id`, `chapter_id`, or `version_id` exist (see
    `feedback.service.record_signal`): this endpoint is fired on every accept/reject click from
    the UI and must stay a fast, spurious-404-free write path even if the frontend has slightly
    stale state.

    After the signal is recorded, `feedback.weights.recompute_accuracy_weight` recomputes and
    persists `body.institution_id`'s `accuracy_weight` from its full signal history. This is a
    side effect only — the response body is still just the persisted `FeedbackSignal`, unchanged
    from TASK-E09-1.
    """
    signal = await record_signal(
        db, body.institution_id, body.chapter_id, body.version_id, body.signal_type
    )
    await recompute_accuracy_weight(db, body.institution_id)
    return signal
