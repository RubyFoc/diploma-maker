"""Tests for TASK-E05-2 (formatting-sample upload + parser).

Builds tiny `.docx` fixtures on the fly with `python-docx` rather than committing binary
fixtures, and exercises the happy path plus the fail-closed paths (invalid file, missing form
field) through the HTTP layer via `client` (see `conftest.py`).
"""

import shutil
from io import BytesIO

import pytest
from docx import Document
from docx.shared import Mm, Pt
from fastapi.testclient import TestClient

from diploma_backend.formatting.upload import UPLOADS_DIR


@pytest.fixture(autouse=True)
def _cleanup_uploads_dir():
    """Remove any files this test module writes to the shared `uploads/` directory."""
    yield
    if UPLOADS_DIR.exists():
        shutil.rmtree(UPLOADS_DIR)


def _build_valid_docx() -> bytes:
    document = Document()
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(20)
    section.bottom_margin = Mm(20)
    section.left_margin = Mm(30)
    section.right_margin = Mm(15)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style.font.size = Pt(14)

    document.add_paragraph("Some prior research [1] found similar results, and [2] confirms it.")

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_upload_creates_config_with_parsed_fields(client: TestClient) -> None:
    docx_bytes = _build_valid_docx()

    response = client.post(
        "/formatting/institution-configs/upload",
        data={"institution_name": "Belarusian State University"},
        files={"file": ("sample.docx", docx_bytes, "application/vnd.openxmlformats")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["institution_name"] == "Belarusian State University"
    assert body["source"] == "upload"
    assert body["page"]["size"] == "A4"
    assert body["page"]["orientation"] == "portrait"
    assert body["page"]["margins_mm"] == {"top": 20, "bottom": 20, "left": 30, "right": 15}
    assert body["font"]["family"] == "Times New Roman"
    assert body["font"]["size_pt"] == 14
    assert body["citation_style"] == "GOST"
    assert body["headings"] == {"h1": {}, "h2": {}, "h3": {}}
    assert body["toc_rules"] == {}
    assert body["accuracy_weight"] == 0.0
    assert body["raw_sample_reference"] == body["institution_id"]
    assert (UPLOADS_DIR / f"{body['raw_sample_reference']}.docx").exists()


def test_upload_invalid_file_returns_4xx_not_500(client: TestClient) -> None:
    response = client.post(
        "/formatting/institution-configs/upload",
        data={"institution_name": "Some University"},
        files={"file": ("sample.docx", b"not a real docx file", "application/octet-stream")},
    )

    assert 400 <= response.status_code < 500


def test_upload_reuses_existing_config_for_same_name_case_insensitive(client: TestClient) -> None:
    first_response = client.post(
        "/formatting/institution-configs/upload",
        data={"institution_name": "БГУИЯ"},
        files={"file": ("sample.docx", _build_valid_docx(), "application/vnd.openxmlformats")},
    )
    assert first_response.status_code == 201
    first_id = first_response.json()["institution_id"]

    second_response = client.post(
        "/formatting/institution-configs/upload",
        data={"institution_name": " бгуия "},
        files={"file": ("sample.docx", _build_valid_docx(), "application/vnd.openxmlformats")},
    )

    assert second_response.status_code == 201
    assert second_response.json()["institution_id"] == first_id

    listing = client.get("/formatting/institution-configs").json()
    assert sum(1 for config in listing if config["institution_name"] == "БГУИЯ") == 1


def test_upload_missing_institution_name_returns_4xx(client: TestClient) -> None:
    docx_bytes = _build_valid_docx()

    response = client.post(
        "/formatting/institution-configs/upload",
        files={"file": ("sample.docx", docx_bytes, "application/vnd.openxmlformats")},
    )

    assert 400 <= response.status_code < 500
