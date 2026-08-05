"""Institution config document shape (ADR-0005, TASK-E05-1).

Defines the exact JSON schema `docs/architecture/decisions.md` locks in for per-institution
formatting rules. E06 (export) and E09 (accuracy-weight adjustment) consume this shape directly;
changing field names/structure later requires a migration across every stored config.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

# "auto" (ADR-0005's 2026-08-05 addendum) marks a config web-discovered by
# `formatting.discovery` — distinct from a verified upload or the seeded GOST default, hence its
# own, lower `accuracy_weight` (0.3, vs. an upload's 0.0-until-verified or a seed's 1.0).
Source = Literal["upload", "seed", "auto"]
PageSize = Literal["A4", "Letter"]
Orientation = Literal["portrait", "landscape"]
CitationStyle = Literal["APA", "GOST", "MLA", "custom"]


class MarginsMm(BaseModel):
    """Page margins in millimeters."""

    top: float
    bottom: float
    left: float
    right: float


class PageConfig(BaseModel):
    """Page size, orientation, and margins."""

    size: PageSize
    orientation: Orientation
    margins_mm: MarginsMm


class FontConfig(BaseModel):
    """Body font family, point size, and line spacing."""

    family: str
    size_pt: float
    line_spacing: float


class HeadingStyle(BaseModel):
    """Per-level heading style. Fields are open-ended (ADR-0005 defines `{}`, no fixed keys),
    so extras are accepted rather than rejected.
    """

    model_config = {"extra": "allow"}


class Headings(BaseModel):
    """Heading styles for the three levels the schema names explicitly."""

    h1: HeadingStyle = Field(default_factory=HeadingStyle)
    h2: HeadingStyle = Field(default_factory=HeadingStyle)
    h3: HeadingStyle = Field(default_factory=HeadingStyle)


class InstitutionConfig(BaseModel):
    """Institution formatting config document, matching ADR-0005's schema exactly.

    `institution_id` is the document's unique identifier used by
    `formatting.service.get_institution_config`. `citation_rules` and `toc_rules` are
    open-ended (ADR-0005 defines both as `{}`); this module does not interpret their contents —
    that belongs to TASK-E05-2 (parser) and E04 (citation verification).
    """

    institution_id: str
    institution_name: str
    source: Source
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page: PageConfig
    font: FontConfig
    headings: Headings
    citation_style: CitationStyle
    citation_rules: dict = Field(default_factory=dict)
    toc_rules: dict = Field(default_factory=dict)
    accuracy_weight: float
    raw_sample_reference: str
