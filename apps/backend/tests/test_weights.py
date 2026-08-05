"""Tests for template `accuracy_weight` adjustment logic (TASK-E09-2): the approval-ratio
formula in `feedback.weights`, `formatting.service.update_accuracy_weight`, and the
`POST /feedback/signals` endpoint's side effect of recomputing that weight.
"""

from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.feedback.service import record_signal
from diploma_backend.feedback.weights import recompute_accuracy_weight
from diploma_backend.formatting.models import (
    FontConfig,
    Headings,
    InstitutionConfig,
    MarginsMm,
    PageConfig,
)
from diploma_backend.formatting.service import (
    create_institution_config,
    get_institution_config,
    update_accuracy_weight,
)


def _db() -> AsyncIOMotorDatabase:
    return AsyncMongoMockClient()["diploma_maker_test"]


def _build_config(institution_id: str, accuracy_weight: float = 0.5) -> InstitutionConfig:
    return InstitutionConfig(
        institution_id=institution_id,
        institution_name="Test University",
        source="upload",
        page=PageConfig(
            size="A4",
            orientation="portrait",
            margins_mm=MarginsMm(top=20, bottom=20, left=30, right=15),
        ),
        font=FontConfig(family="Times New Roman", size_pt=14, line_spacing=1.5),
        headings=Headings(),
        citation_style="GOST",
        citation_rules={},
        toc_rules={},
        accuracy_weight=accuracy_weight,
        raw_sample_reference="",
    )


async def test_update_accuracy_weight_updates_existing_config() -> None:
    db = _db()
    config = _build_config("mit", accuracy_weight=0.5)
    await create_institution_config(db, config)

    updated = await update_accuracy_weight(db, "mit", 0.75)

    assert updated is not None
    assert updated.accuracy_weight == 0.75
    assert updated.updated_at != config.updated_at

    refetched = await get_institution_config(db, "mit")
    assert refetched is not None
    assert refetched.accuracy_weight == 0.75


async def test_update_accuracy_weight_returns_none_for_missing_institution() -> None:
    db = _db()
    result = await update_accuracy_weight(db, "does-not-exist", 0.75)
    assert result is None


async def test_recompute_accuracy_weight_returns_none_with_no_signals() -> None:
    db = _db()
    await create_institution_config(db, _build_config("mit", accuracy_weight=1.0))

    result = await recompute_accuracy_weight(db, "mit")

    assert result is None
    config = await get_institution_config(db, "mit")
    assert config is not None
    assert config.accuracy_weight == 1.0


async def test_recompute_accuracy_weight_returns_none_with_only_edit_signals() -> None:
    db = _db()
    await create_institution_config(db, _build_config("mit", accuracy_weight=1.0))
    await record_signal(db, "mit", "chapter-1", "version-1", "edit")
    await record_signal(db, "mit", "chapter-1", "version-2", "edit")

    result = await recompute_accuracy_weight(db, "mit")

    assert result is None
    config = await get_institution_config(db, "mit")
    assert config is not None
    assert config.accuracy_weight == 1.0


async def test_recompute_accuracy_weight_computes_ratio_for_mixed_signals() -> None:
    db = _db()
    await create_institution_config(db, _build_config("mit", accuracy_weight=0.0))
    await record_signal(db, "mit", "chapter-1", "version-1", "approve")
    await record_signal(db, "mit", "chapter-1", "version-2", "approve")
    await record_signal(db, "mit", "chapter-1", "version-3", "approve")
    await record_signal(db, "mit", "chapter-1", "version-4", "reject")

    result = await recompute_accuracy_weight(db, "mit")

    assert result == 0.75
    config = await get_institution_config(db, "mit")
    assert config is not None
    assert config.accuracy_weight == 0.75


async def test_recompute_accuracy_weight_all_rejections_yields_zero() -> None:
    db = _db()
    await create_institution_config(db, _build_config("mit", accuracy_weight=0.5))
    await record_signal(db, "mit", "chapter-1", "version-1", "reject")
    await record_signal(db, "mit", "chapter-1", "version-2", "reject")

    result = await recompute_accuracy_weight(db, "mit")

    assert result == 0.0


async def test_recompute_accuracy_weight_all_approvals_yields_one() -> None:
    db = _db()
    await create_institution_config(db, _build_config("mit", accuracy_weight=0.5))
    await record_signal(db, "mit", "chapter-1", "version-1", "approve")
    await record_signal(db, "mit", "chapter-1", "version-2", "approve")

    result = await recompute_accuracy_weight(db, "mit")

    assert result == 1.0


async def test_recompute_accuracy_weight_returns_none_for_nonexistent_institution() -> None:
    db = _db()
    await record_signal(db, "ghost-school", "chapter-1", "version-1", "approve")

    result = await recompute_accuracy_weight(db, "ghost-school")

    assert result is None


async def test_feedback_signal_endpoint_updates_accuracy_weight() -> None:
    """A 3rd signal (2nd approval, after a pre-existing 1 approve + 1 reject) via the endpoint
    should leave the institution's stored `accuracy_weight` at the new 2/3 ratio.
    """
    from diploma_backend.db import get_database
    from diploma_backend.main import app

    db = _db()
    await create_institution_config(db, _build_config("mit", accuracy_weight=0.5))
    await record_signal(db, "mit", "chapter-1", "version-1", "approve")
    await record_signal(db, "mit", "chapter-1", "version-2", "reject")

    app.dependency_overrides[get_database] = lambda: db
    try:
        response = TestClient(app).post(
            "/feedback/signals",
            json={
                "institution_id": "mit",
                "chapter_id": "chapter-1",
                "version_id": "version-3",
                "signal_type": "approve",
            },
        )
    finally:
        app.dependency_overrides.pop(get_database, None)

    assert response.status_code == 201

    config = await get_institution_config(db, "mit")
    assert config is not None
    assert config.accuracy_weight == 2 / 3
