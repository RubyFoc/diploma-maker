"""Template `accuracy_weight` adjustment logic (E09, TASK-E09-2).

Composes `feedback.service.list_signals_for_institution` (TASK-E09-1's audit log) and
`formatting.service.update_accuracy_weight` to turn a growing history of approve/reject/edit
signals into a single `InstitutionConfig.accuracy_weight` number.

Adjustment rule (deliberately chosen, not the only possible one): `accuracy_weight` is the
**approval ratio across the institution's full signal history** —
`approvals / (approvals + rejections)` — recomputed from scratch on every new signal, rather than
an incremental per-signal bump/decay. An incremental step-per-signal scheme would drift
unboundedly with volume and effectively forget older signals as new ones keep nudging the same
direction; recomputing the full ratio keeps the weight anchored to the institution's overall
track record, and keeps every adjustment traceable back to the exact signal rows that produced it
(the E09 architect's auditability note), since the signal log itself is authoritative and this
function never mutates it.

`"edit"` signals are excluded from the ratio entirely — this is a deliberate choice, not an
oversight. Per `feedback.models`'s own docstring, no UI flow emits `"edit"` yet (there's no
edit-then-resubmit path to observe), and unlike `"approve"`/`"reject"`, "the user edited it" isn't
cleanly positive or negative: an edit could be a minor tweak to an otherwise-good draft or a
near-total rewrite. A future iteration could fold edits in as a partial-negative signal once a
real edit-then-resubmit flow exists to calibrate that weighting against, but guessing at a
partial-credit value now would just be an arbitrary number.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.feedback.service import list_signals_for_institution
from diploma_backend.formatting.service import update_accuracy_weight


def _compute_approval_ratio(approvals: int, rejections: int) -> float:
    """Compute `approvals / (approvals + rejections)`, clamped to `[0.0, 1.0]`.

    Callers must only call this when `approvals + rejections > 0` (division by zero otherwise).
    The clamp is defensive belt-and-suspenders only: the ratio of two non-negative counts is
    already mathematically guaranteed to land in `[0.0, 1.0]`, so this should never actually
    trigger — it exists purely as a hard safety bound against any future change to the formula.
    """
    ratio = approvals / (approvals + rejections)
    return max(0.0, min(1.0, ratio))


async def recompute_accuracy_weight(
    db: AsyncIOMotorDatabase, institution_id: str
) -> float | None:
    """Recompute and persist `institution_id`'s `accuracy_weight` from its full signal history.

    Returns the new weight, or `None` if there is nothing to compute from (no signals at all, or
    only `"edit"` signals so far) — in that case the stored `accuracy_weight` is left untouched,
    so an institution with no real approve/reject feedback yet keeps whatever weight it started
    with (e.g. a seeded default's `1.0` or an upload's `0.0`) instead of being reset to a
    division-by-zero default. Also returns `None`, without raising, if `institution_id` doesn't
    match any stored config (mirrors `formatting.service.update_accuracy_weight`'s miss-handling);
    this shouldn't normally happen since signals are only ever recorded against real institutions.
    """
    signals = await list_signals_for_institution(db, institution_id)
    approvals = sum(1 for signal in signals if signal.signal_type == "approve")
    rejections = sum(1 for signal in signals if signal.signal_type == "reject")
    if approvals + rejections == 0:
        return None

    new_weight = _compute_approval_ratio(approvals, rejections)
    updated_config = await update_accuracy_weight(db, institution_id, new_weight)
    if updated_config is None:
        return None
    return updated_config.accuracy_weight
