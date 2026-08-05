"""Tests for TASK-E05-3 (university dropdown/selection endpoints).

Exercises `GET /formatting/institution-configs` and
`GET /formatting/institution-configs/{institution_id}` through the HTTP layer via `client` (see
`conftest.py`), reusing the `_build_config`/`_fake_db` helpers from `test_formatting.py` to seed
the in-memory Mongo fake directly (these endpoints are pure wiring around already-tested storage
functions, so tests focus on the HTTP contract, not storage behavior).
"""

from fastapi.testclient import TestClient
from test_formatting import _build_config, _fake_db

from diploma_backend.formatting.service import create_institution_config


def test_list_returns_empty_list_when_no_configs_exist(client: TestClient) -> None:
    response = client.get("/formatting/institution-configs")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_returns_created_configs(client: TestClient) -> None:
    db = _fake_db(client)
    first = _build_config("bsu-2026")
    second = _build_config("bnu-2026")
    second.institution_name = "Belarusian National University"
    await create_institution_config(db, first)
    await create_institution_config(db, second)

    response = client.get("/formatting/institution-configs")

    assert response.status_code == 200
    body = response.json()
    assert {item["institution_id"] for item in body} == {"bsu-2026", "bnu-2026"}
    assert {item["institution_name"] for item in body} == {
        "Belarusian State University",
        "Belarusian National University",
    }


async def test_get_by_id_returns_matching_config(client: TestClient) -> None:
    db = _fake_db(client)
    config = _build_config("bsu-2026")
    await create_institution_config(db, config)

    response = client.get("/formatting/institution-configs/bsu-2026")

    assert response.status_code == 200
    body = response.json()
    assert body["institution_id"] == "bsu-2026"
    assert body["institution_name"] == "Belarusian State University"
    assert body["citation_style"] == "GOST"


def test_get_by_id_404s_for_unknown_id(client: TestClient) -> None:
    response = client.get("/formatting/institution-configs/does-not-exist")

    assert response.status_code == 404
