"""Formatting-sample upload endpoint (TASK-E05-2).

`POST /formatting/institution-configs/upload` turns a `.docx` formatting sample into a stored
`InstitutionConfig` (ADR-0005). Selecting/listing institutions by name (TASK-E05-3) is a
separate, not-yet-built endpoint.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.db import get_database
from diploma_backend.formatting.models import Headings, InstitutionConfig
from diploma_backend.formatting.service import create_institution_config
from diploma_backend.formatting.upload import (
    FormattingSampleParseError,
    parse_formatting_sample,
    save_uploaded_sample,
)

router = APIRouter(prefix="/formatting", tags=["formatting"])


@router.post(
    "/institution-configs/upload",
    response_model=InstitutionConfig,
    status_code=status.HTTP_201_CREATED,
)
async def upload_institution_config(
    institution_name: str = Form(min_length=1),
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InstitutionConfig:
    """Save `file` as a raw formatting sample and create an `InstitutionConfig` from it.

    Parses page/font/citation-style fields via `formatting.upload.parse_formatting_sample`.
    `headings`, `citation_rules`, and `toc_rules` are left at ADR-0005's empty-dict defaults and
    `accuracy_weight` at `0.0` — extracting those is out of scope for this task. Raises
    `HTTPException(422)` if `file` isn't a parseable `.docx` sample (fail-closed: this endpoint
    never guesses page/font values it couldn't read).
    """
    content = await file.read()

    try:
        parsed = parse_formatting_sample(content)
    except FormattingSampleParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    file_id = save_uploaded_sample(content)

    config = InstitutionConfig(
        institution_id=file_id,
        institution_name=institution_name,
        source="upload",
        page=parsed.page,
        font=parsed.font,
        headings=Headings(),
        citation_style=parsed.citation_style,
        citation_rules={},
        toc_rules={},
        accuracy_weight=0.0,
        raw_sample_reference=file_id,
    )
    return await create_institution_config(db, config)
