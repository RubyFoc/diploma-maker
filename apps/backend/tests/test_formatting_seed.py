"""Tests for the default GOST 7.32-2017 institution config seed (`formatting.seed`)."""

from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.formatting.seed import (
    GOST_DEFAULT_INSTITUTION_ID,
    build_default_gost_config,
    ensure_default_gost_config,
)
from diploma_backend.formatting.service import (
    create_institution_config,
    get_institution_config,
    list_institution_configs,
)
from diploma_backend.main import app


def _fake_db(client: TestClient):
    return app.dependency_overrides[get_database]()


def test_build_default_gost_config_matches_published_standard() -> None:
    config = build_default_gost_config()

    assert config.institution_id == GOST_DEFAULT_INSTITUTION_ID
    assert config.source == "seed"
    assert config.page.margins_mm.model_dump() == {
        "top": 20,
        "bottom": 20,
        "left": 30,
        "right": 15,
    }
    assert config.font.family == "Times New Roman"
    assert config.font.size_pt == 14
    assert config.font.line_spacing == 1.5
    assert config.citation_style == "GOST"


async def test_ensure_default_gost_config_inserts_when_missing(client: TestClient) -> None:
    db = _fake_db(client)

    assert await get_institution_config(db, GOST_DEFAULT_INSTITUTION_ID) is None

    await ensure_default_gost_config(db)

    stored = await get_institution_config(db, GOST_DEFAULT_INSTITUTION_ID)
    assert stored is not None
    assert stored.institution_name == "ГОСТ 7.32-2017 (default)"

    configs = await list_institution_configs(db)
    assert [c.institution_id for c in configs] == [GOST_DEFAULT_INSTITUTION_ID]


async def test_ensure_default_gost_config_is_idempotent(client: TestClient) -> None:
    db = _fake_db(client)

    await ensure_default_gost_config(db)
    await ensure_default_gost_config(db)
    await ensure_default_gost_config(db)

    configs = await list_institution_configs(db)
    assert len(configs) == 1


async def test_ensure_default_gost_config_does_not_overwrite_edited_weight(
    client: TestClient,
) -> None:
    """A restart must not reset `accuracy_weight` back to 1.0 once TASK-E09-2's weight-adjustment
    logic (or a manual edit) has changed it — `ensure_default_gost_config` only inserts on a
    true miss, never updates an existing row."""
    db = _fake_db(client)
    seeded = build_default_gost_config()
    edited = seeded.model_copy(update={"accuracy_weight": 0.42})
    await create_institution_config(db, edited)

    await ensure_default_gost_config(db)

    stored = await get_institution_config(db, GOST_DEFAULT_INSTITUTION_ID)
    assert stored is not None
    assert stored.accuracy_weight == 0.42
