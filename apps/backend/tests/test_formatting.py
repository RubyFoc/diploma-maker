"""Tests for TASK-E05-1 (institution config schema + MongoDB storage), using the in-memory Mongo
fake from `conftest.py`. `client` (a FastAPI `TestClient`) is only used here for its
dependency-override wiring of `get_database`, since this module has no HTTP routes yet.
"""

from datetime import UTC, timedelta

from fastapi.testclient import TestClient

from diploma_backend.db import get_database
from diploma_backend.formatting.models import (
    FontConfig,
    Headings,
    HeadingStyle,
    InstitutionConfig,
    MarginsMm,
    PageConfig,
)
from diploma_backend.formatting.service import (
    create_institution_config,
    get_institution_config,
    list_institution_configs,
)
from diploma_backend.main import app


def _build_config(institution_id: str = "bsu-2026") -> InstitutionConfig:
    return InstitutionConfig(
        institution_id=institution_id,
        institution_name="Belarusian State University",
        source="seed",
        page=PageConfig(
            size="A4",
            orientation="portrait",
            margins_mm=MarginsMm(top=20, bottom=20, left=30, right=15),
        ),
        font=FontConfig(family="Times New Roman", size_pt=14, line_spacing=1.5),
        headings=Headings(
            h1=HeadingStyle(bold=True, size_pt=16),
            h2=HeadingStyle(bold=True, size_pt=14),
            h3=HeadingStyle(italic=True),
        ),
        citation_style="GOST",
        citation_rules={"style": "numeric"},
        toc_rules={"max_depth": 3},
        accuracy_weight=0.8,
        raw_sample_reference="file-123",
    )


def _fake_db(client: TestClient):
    return app.dependency_overrides[get_database]()


async def test_create_persists_all_adr0005_fields(client: TestClient) -> None:
    db = _fake_db(client)
    config = _build_config()

    created = await create_institution_config(db, config)
    assert created == config

    stored = await db["institution_configs"].find_one({"institution_id": "bsu-2026"})
    assert stored is not None
    assert stored["institution_name"] == "Belarusian State University"
    assert stored["source"] == "seed"
    assert stored["page"]["size"] == "A4"
    assert stored["page"]["orientation"] == "portrait"
    assert stored["page"]["margins_mm"] == {"top": 20, "bottom": 20, "left": 30, "right": 15}
    assert stored["font"] == {"family": "Times New Roman", "size_pt": 14, "line_spacing": 1.5}
    assert stored["headings"]["h1"] == {"bold": True, "size_pt": 16}
    assert stored["citation_style"] == "GOST"
    assert stored["citation_rules"] == {"style": "numeric"}
    assert stored["toc_rules"] == {"max_depth": 3}
    assert stored["accuracy_weight"] == 0.8
    assert stored["raw_sample_reference"] == "file-123"
    assert "created_at" in stored
    assert "updated_at" in stored


async def test_get_by_id_returns_same_document(client: TestClient) -> None:
    db = _fake_db(client)
    config = _build_config()
    await create_institution_config(db, config)

    fetched = await get_institution_config(db, "bsu-2026")
    assert fetched is not None
    # MongoDB truncates datetimes to millisecond precision and returns them naive (UTC), so
    # compare timestamps loosely and compare every other field exactly.
    assert abs(fetched.created_at.replace(tzinfo=UTC) - config.created_at) < timedelta(
        milliseconds=1
    )
    assert abs(fetched.updated_at.replace(tzinfo=UTC) - config.updated_at) < timedelta(
        milliseconds=1
    )
    assert fetched.model_dump(exclude={"created_at", "updated_at"}) == config.model_dump(
        exclude={"created_at", "updated_at"}
    )


async def test_get_by_missing_id_returns_none(client: TestClient) -> None:
    db = _fake_db(client)
    fetched = await get_institution_config(db, "does-not-exist")
    assert fetched is None


async def test_list_returns_multiple_created_configs(client: TestClient) -> None:
    db = _fake_db(client)
    first = _build_config("bsu-2026")
    second = _build_config("bnu-2026")
    second.institution_name = "Belarusian National University"

    await create_institution_config(db, first)
    await create_institution_config(db, second)

    configs = await list_institution_configs(db)
    assert {config.institution_id for config in configs} == {"bsu-2026", "bnu-2026"}
