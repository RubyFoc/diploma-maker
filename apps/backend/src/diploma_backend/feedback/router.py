"""Feedback signal capture endpoint (TASK-E09-1).

Composes `feedback.service` (signal storage) without modifying its internals. This is the
backend half of "approve/reject/edit signal capture (UI + API)" — recording the raw signal only,
no `accuracy_weight` adjustment (that's TASK-E09-2, a separate, still-blocked task).
"""

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.db import get_database
from diploma_backend.feedback.models import FeedbackSignal, SignalType
from diploma_backend.feedback.service import record_signal

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
    """
    return await record_signal(
        db, body.institution_id, body.chapter_id, body.version_id, body.signal_type
    )
