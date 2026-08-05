"""Tests for the auto-discovery of institution formatting requirements (ADR-0005 addendum,
2026-08-05) — `formatting.discovery` and its `POST /formatting/institution-configs/auto-detect`
route.

HTTP calls (both the DuckDuckGo search and per-page fetches) are mocked with `respx` — no real
network access, matching `test_source_search.py`'s established pattern for external-API mocking.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from diploma_backend.formatting.discovery import (
    DiscoveryResult,
    FormattingDiscoveryError,
    discover_institution_config,
    extract_font,
    extract_margins_mm,
    fetch_page_text,
    search_formatting_pages,
)
from diploma_backend.formatting.models import FontConfig, MarginsMm

_DDG_URL = "https://html.duckduckgo.com/html/"

_SAMPLE_TEXT = (
    "поля: левое – 30 мм, верхнее – 20 мм, правое – 15 мм, нижнее – 20 мм; "
    "ориентация: книжная; шрифт: Times New Roman; кегель: - 14 пт (пунктов) в основном "
    "тексте; интервал: полуторный"
)

_IRRELEVANT_TEXT = "Это страница про историю университета, без сведений о полях и шрифте."


def _ddg_html(links: list[str]) -> str:
    import urllib.parse

    anchors = "".join(
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg={urllib.parse.quote(url, safe="")}'
        f'&rut=abc">Result</a>'
        for url in links
    )
    return f"<html><body>{anchors}</body></html>"


# --- search_formatting_pages -------------------------------------------------------------


@respx.mock
async def test_search_formatting_pages_parses_ddg_result_links() -> None:
    links = [
        "https://studfile.net/preview/12345/",
        "https://example.edu/methodics.html",
        "https://example.edu/guide.pdf",
    ]
    respx.get(_DDG_URL).mock(return_value=httpx.Response(200, text=_ddg_html(links)))

    results = await search_formatting_pages("Example University")

    assert results == links


@respx.mock
async def test_search_formatting_pages_respects_limit() -> None:
    links = [f"https://example.edu/page{i}.html" for i in range(10)]
    respx.get(_DDG_URL).mock(return_value=httpx.Response(200, text=_ddg_html(links)))

    results = await search_formatting_pages("Example University", limit=3)

    assert results == links[:3]


@respx.mock
async def test_search_formatting_pages_raises_on_http_failure() -> None:
    respx.get(_DDG_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(FormattingDiscoveryError):
        await search_formatting_pages("Example University")


@respx.mock
async def test_search_formatting_pages_raises_on_network_error() -> None:
    respx.get(_DDG_URL).mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(FormattingDiscoveryError):
        await search_formatting_pages("Example University")


# --- fetch_page_text ----------------------------------------------------------------------


@respx.mock
async def test_fetch_page_text_strips_html() -> None:
    url = "https://example.edu/methodics.html"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<html><body><p>Times   New\nRoman</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    text = await fetch_page_text(url)

    assert text == "Times New Roman"


@respx.mock
async def test_fetch_page_text_decodes_html_entities() -> None:
    """Regression test: real pages commonly write margin dashes as `&ndash;` rather than a
    literal '–' — if entities aren't decoded before the extraction regexes run, `[-–:]` never
    matches and every margin/font lookup silently fails on otherwise-perfectly-good pages."""
    url = "https://example.edu/methodics-entities.html"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<p>слева &ndash; 30 мм</p>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    text = await fetch_page_text(url)

    assert text == "слева – 30 мм"
    assert extract_margins_mm("поля: левое – 30 мм, верхнее – 20 мм, правое – 15 мм, нижнее – 20 мм") is not None


@respx.mock
async def test_fetch_page_text_returns_none_for_non_html() -> None:
    url = "https://example.edu/guide.pdf"
    respx.get(url).mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
    )

    assert await fetch_page_text(url) is None


@respx.mock
async def test_fetch_page_text_returns_none_on_network_failure() -> None:
    url = "https://example.edu/unreachable.html"
    respx.get(url).mock(side_effect=httpx.ConnectTimeout("timed out"))

    assert await fetch_page_text(url) is None


@respx.mock
async def test_fetch_page_text_returns_none_on_non_2xx() -> None:
    url = "https://example.edu/missing.html"
    respx.get(url).mock(return_value=httpx.Response(404, text="not found"))

    assert await fetch_page_text(url) is None


# --- extract_margins_mm / extract_font -----------------------------------------------------


def test_extract_margins_mm_from_real_example_text() -> None:
    assert extract_margins_mm(_SAMPLE_TEXT) == MarginsMm(top=20, bottom=20, left=30, right=15)


def test_extract_margins_mm_returns_none_when_incomplete() -> None:
    assert extract_margins_mm("левое – 30 мм, верхнее – 20 мм") is None


def test_extract_margins_mm_returns_none_for_irrelevant_text() -> None:
    assert extract_margins_mm(_IRRELEVANT_TEXT) is None


def test_extract_margins_mm_handles_adverb_forms_and_shared_top_bottom() -> None:
    """Regression test from a real page (dissergrad.com) found during manual verification: guides
    commonly phrase margins as adverbs ("слева"/"справа"/"сверху"/"снизу") rather than the
    adjective forms ("левое"/"правое"/"верхнее"/"нижнее"), and state top+bottom together with one
    shared value ("сверху и снизу – 20 мм") instead of repeating the number for each side."""
    text = "размер полей: справа – 10 мм, слева – 30 мм, сверху и снизу – 20 мм."
    assert extract_margins_mm(text) == MarginsMm(top=20, bottom=20, left=30, right=10)


def test_extract_font_from_real_example_text() -> None:
    assert extract_font(_SAMPLE_TEXT) == FontConfig(
        family="Times New Roman", size_pt=14.0, line_spacing=1.5
    )


def test_extract_font_defaults_line_spacing_when_absent() -> None:
    text = "шрифт: Times New Roman; кегль - 14 пт"
    font = extract_font(text)
    assert font is not None
    assert font.line_spacing == 1.5


def test_extract_font_returns_none_for_irrelevant_text() -> None:
    assert extract_font(_IRRELEVANT_TEXT) is None


# --- discover_institution_config ------------------------------------------------------------


@respx.mock
async def test_discover_institution_config_found_skips_pdf_and_uses_first_valid_html() -> None:
    links = ["https://example.edu/guide.pdf", "https://studfile.net/preview/12345/"]
    respx.get(_DDG_URL).mock(return_value=httpx.Response(200, text=_ddg_html(links)))
    respx.get(links[0]).mock(
        return_value=httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    )
    respx.get(links[1]).mock(
        return_value=httpx.Response(
            200, text=f"<html><body>{_SAMPLE_TEXT}</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    result = await discover_institution_config("Example University")

    assert result.status == "found"
    assert result.source_url == links[1]
    assert result.config is not None
    assert result.config.institution_name == "Example University"
    assert result.config.source == "auto"
    assert result.config.accuracy_weight == 0.3
    assert result.config.page.margins_mm == MarginsMm(top=20, bottom=20, left=30, right=15)
    assert result.config.font == FontConfig(
        family="Times New Roman", size_pt=14.0, line_spacing=1.5
    )
    assert result.config.citation_style == "GOST"
    assert result.config.raw_sample_reference == ""


@respx.mock
async def test_discover_institution_config_not_found_when_no_page_has_data() -> None:
    links = ["https://example.edu/history.html"]
    respx.get(_DDG_URL).mock(return_value=httpx.Response(200, text=_ddg_html(links)))
    respx.get(links[0]).mock(
        return_value=httpx.Response(
            200, text=f"<html><body>{_IRRELEVANT_TEXT}</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    result = await discover_institution_config("Example University")

    assert result == DiscoveryResult(status="not_found", config=None, source_url=None)


@respx.mock
async def test_discover_institution_config_propagates_search_error() -> None:
    respx.get(_DDG_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(FormattingDiscoveryError):
        await discover_institution_config("Example University")


# --- router ---------------------------------------------------------------------------------


def test_auto_detect_endpoint_returns_201_on_found(client: TestClient, monkeypatch) -> None:
    async def _fake_discover(university_name: str) -> DiscoveryResult:
        from diploma_backend.formatting.models import (
            FontConfig,
            Headings,
            InstitutionConfig,
            MarginsMm,
            PageConfig,
        )

        config = InstitutionConfig(
            institution_id="auto-test-id",
            institution_name=university_name,
            source="auto",
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
            accuracy_weight=0.3,
            raw_sample_reference="",
        )
        return DiscoveryResult(status="found", config=config, source_url="https://example.edu/x")

    monkeypatch.setattr(
        "diploma_backend.formatting.router.discover_institution_config", _fake_discover
    )

    response = client.post(
        "/formatting/institution-configs/auto-detect",
        json={"institution_name": "Example University"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["institution_name"] == "Example University"
    assert body["source"] == "auto"
    assert body["accuracy_weight"] == 0.3


def test_auto_detect_endpoint_returns_404_on_not_found(client: TestClient, monkeypatch) -> None:
    async def _fake_discover(university_name: str) -> DiscoveryResult:
        return DiscoveryResult(status="not_found", config=None, source_url=None)

    monkeypatch.setattr(
        "diploma_backend.formatting.router.discover_institution_config", _fake_discover
    )

    response = client.post(
        "/formatting/institution-configs/auto-detect",
        json={"institution_name": "Unknown University"},
    )

    assert response.status_code == 404
    assert "Unknown University" in response.json()["detail"]


def test_auto_detect_endpoint_returns_502_on_discovery_error(
    client: TestClient, monkeypatch
) -> None:
    async def _fake_discover(university_name: str):
        raise FormattingDiscoveryError("DuckDuckGo search failed: ConnectError")

    monkeypatch.setattr(
        "diploma_backend.formatting.router.discover_institution_config", _fake_discover
    )

    response = client.post(
        "/formatting/institution-configs/auto-detect",
        json={"institution_name": "Example University"},
    )

    assert response.status_code == 502


def test_auto_detect_endpoint_returns_422_on_empty_institution_name(client: TestClient) -> None:
    response = client.post(
        "/formatting/institution-configs/auto-detect",
        json={"institution_name": ""},
    )

    assert response.status_code == 422
