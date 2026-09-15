"""Tier 2's visual agent — the LLM decision call is mocked (a real Opus 5 call needs a live key
this environment doesn't have); the browser interactions run against real Chromium and a fake
page (test_render.py already covers real navigation)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest
from playwright.async_api import async_playwright

from app.scraping.visual_agent import VisualAction, explore_visually


def _mock_response(action: VisualAction, tokens_in: int = 100, tokens_out: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        parsed_output=action, usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out)
    )


@pytest.fixture
def fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """A mock `.parse()` the test configures with `return_value`/`side_effect`, wired into the
    module's `anthropic.AsyncAnthropic` the same way test_extraction.py mocks the extraction call."""
    mock_parse = AsyncMock()
    monkeypatch.setattr(
        anthropic, "AsyncAnthropic", lambda **_: SimpleNamespace(messages=SimpleNamespace(parse=mock_parse))
    )
    return mock_parse


async def test_stops_immediately_when_the_model_says_done(fake_anthropic: AsyncMock) -> None:
    done = VisualAction(action="done", reasoning="Nothing more to see.")
    fake_anthropic.return_value = _mock_response(done)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            result = await explore_visually(browser, "https://example.com", max_steps=5)
        finally:
            await browser.close()

    assert result.pages == []
    assert result.tokens_in == 100
    assert result.tokens_out == 20
    fake_anthropic.assert_awaited_once()


async def test_scroll_action_produces_a_rendered_page(fake_anthropic: AsyncMock) -> None:
    fake_anthropic.side_effect = [
        _mock_response(VisualAction(action="scroll_down", reasoning="See more content.")),
        _mock_response(VisualAction(action="done", reasoning="Fully explored.")),
    ]
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            result = await explore_visually(browser, "https://example.com", max_steps=5)
        finally:
            await browser.close()

    assert len(result.pages) == 1
    assert "Example Domain" in result.pages[0].markdown
    assert result.pages[0].screenshot is not None
    assert result.tokens_in == 200
    assert result.tokens_out == 40


async def test_respects_max_steps(fake_anthropic: AsyncMock) -> None:
    scroll = VisualAction(action="scroll_down", reasoning="Keep looking.")
    fake_anthropic.return_value = _mock_response(scroll)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            result = await explore_visually(browser, "https://example.com", max_steps=3)
        finally:
            await browser.close()

    assert fake_anthropic.await_count == 3
    assert len(result.pages) == 3


async def test_unsafe_navigate_target_ends_exploration_without_raising(fake_anthropic: AsyncMock) -> None:
    fake_anthropic.return_value = _mock_response(
        VisualAction(action="navigate", url="http://169.254.169.254/", reasoning="Looks like a link.")
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            result = await explore_visually(browser, "https://example.com", max_steps=5)
        finally:
            await browser.close()

    assert result.pages == []


async def test_a_bad_start_url_returns_an_empty_result(fake_anthropic: AsyncMock) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            result = await explore_visually(browser, "http://localhost:1", max_steps=5)
        finally:
            await browser.close()

    assert result.pages == []
    assert result.tokens_in == 0
    fake_anthropic.assert_not_awaited()
