"""Tier 1 extraction — prompt building and result parsing, against a mocked Anthropic client."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest

from app.scraping import extraction
from app.scraping.extraction import ExtractedOffering, ExtractedProfile, extract_profile
from app.scraping.render import RenderedPage


def _page(url: str, markdown: str) -> RenderedPage:
    return RenderedPage(url=url, final_url=url, status_code=200, markdown=markdown, content_hash="x")


async def test_no_pages_makes_no_call() -> None:
    assert await extract_profile([]) is None


async def test_extract_profile_parses_the_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_profile = ExtractedProfile(
        overview="Acme makes widgets.",
        offerings=[
            ExtractedOffering(
                kind="product",
                name="WidgetPro",
                description="A very good widget.",
                category="Hardware",
                evidence=[{"url": "https://acme.example/products", "quote": "Introducing WidgetPro"}],
            )
        ],
        competencies=[],
    )
    fake_response = SimpleNamespace(
        parsed_output=fake_profile, usage=SimpleNamespace(input_tokens=1234, output_tokens=321)
    )
    mock_parse = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(
        anthropic,
        "AsyncAnthropic",
        lambda **_: SimpleNamespace(messages=SimpleNamespace(parse=mock_parse)),
    )

    page = _page("https://acme.example/products", "# WidgetPro\n\nIntroducing WidgetPro.")
    result = await extract_profile([page])

    assert result is not None
    assert result.profile.overview == "Acme makes widgets."
    assert result.profile.offerings[0].name == "WidgetPro"
    assert result.tokens_in == 1234
    assert result.tokens_out == 321

    call_kwargs = mock_parse.call_args.kwargs
    assert call_kwargs["model"] == extraction.MODEL
    assert call_kwargs["output_format"] is ExtractedProfile
    assert "WidgetPro" in call_kwargs["messages"][0]["content"]


async def test_prompt_truncates_to_the_total_character_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "MAX_TOTAL_PROMPT_CHARS", 50)
    pages = [_page("https://acme.example/a", "x" * 40), _page("https://acme.example/b", "y" * 40)]
    prompt = extraction._build_prompt(pages)
    # The first page's content fits; the second is cut short by the remaining budget.
    assert "x" * 40 in prompt
    assert "y" * 40 not in prompt
