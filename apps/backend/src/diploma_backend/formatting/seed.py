"""Seeds a default GOST 7.32-2017 institution config (ADR-0005's `source="seed"` value).

Before this module existed, `source: Literal["upload", "seed"]` on `InstitutionConfig` had no
actual seed producer anywhere in the codebase — the only way to get a config was to upload a
`.docx` sample first (TASK-E05-2). That leaves a real onboarding gap: a brand-new deployment's
`GET /formatting/institution-configs` dropdown (TASK-E05-3) is empty until someone uploads a
sample, even though this platform's primary target (per ADR-0001's GOST citation-style handling
and the RU/BY geo-fencing in `sources.geo_filter`) is Russian/Belarusian academic writing, which
follows a well-known published standard.

Values below are GOST 7.32-2017's published formatting requirements (margins, font, line
spacing), verified via web search against multiple independent sources (GOST 7.32-2017's own
text and several university methodology guides) rather than guessed:
- Margins: left 30mm, right 15mm, top/bottom 20mm.
- Font: Times New Roman, 14pt, 1.5 line spacing.
- Citation style: GOST (numbered bracketed references, e.g. "[3]").

This is a real published national standard, not a specific university's house style — it exists
so a user has a sensible, standards-compliant starting point before uploading (or instead of
uploading, if their institution just follows the bare standard) rather than an empty dropdown.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from diploma_backend.formatting.models import (
    FontConfig,
    Headings,
    InstitutionConfig,
    MarginsMm,
    PageConfig,
)
from diploma_backend.formatting.service import create_institution_config, get_institution_config

# Fixed, well-known id so `ensure_default_gost_config` is idempotent across restarts (it checks
# for this exact id before inserting) rather than creating a duplicate seed row every time the
# app starts.
GOST_DEFAULT_INSTITUTION_ID = "seed-gost-7-32-2017"


def build_default_gost_config() -> InstitutionConfig:
    """Build (but not persist) the default GOST 7.32-2017 `InstitutionConfig`.

    `raw_sample_reference` is an empty string, not a real uploaded-file id — there is no sample
    document behind this config, unlike an `source="upload"` config's `raw_sample_reference`
    (TASK-E05-2). `accuracy_weight` starts at `1.0` (rather than the `0.0` an upload starts at,
    see `formatting/router.py`'s upload endpoint) since this is a verified published standard,
    not an unvalidated user upload — TASK-E09-2's future weight-adjustment logic should treat
    this as a trusted baseline to adjust away from, not up from zero.
    """
    return InstitutionConfig(
        institution_id=GOST_DEFAULT_INSTITUTION_ID,
        institution_name="ГОСТ 7.32-2017 (default)",
        source="seed",
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
        accuracy_weight=1.0,
        raw_sample_reference="",
    )


async def ensure_default_gost_config(db: AsyncIOMotorDatabase) -> None:
    """Insert the default GOST config if it doesn't already exist. Safe to call on every startup.

    Idempotent via `GOST_DEFAULT_INSTITUTION_ID`: checks `get_institution_config` first and only
    inserts on a cache/database miss, so restarting the app repeatedly never creates duplicates
    or overwrites a config someone has since edited (once E09-2's weight-adjustment logic starts
    mutating `accuracy_weight` on this row, a restart must not reset that back to `1.0`).
    """
    existing = await get_institution_config(db, GOST_DEFAULT_INSTITUTION_ID)
    if existing is not None:
        return
    await create_institution_config(db, build_default_gost_config())
