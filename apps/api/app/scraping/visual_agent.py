"""Tier 2 — the visual agent. Deep mode's escalation for sites Tier 1's static render can't
fully read: content behind tabs, accordions, "load more" buttons, or mega-menus that only appear
after a real interaction.

Deliberately not the `browser-use` library: it hard-pins `anthropic==0.76.0`, which conflicts
with the `anthropic>=1.5.0` app/scraping/extraction.py already needs (client.messages.parse is a
1.x-only API) in the same shared apps/api dependency tree. This is a small, bounded loop built
directly on Playwright and the same Anthropic SDK version the rest of the app uses — one
dependency tree throughout, at the cost of owning this loop ourselves.

The agent only *navigates*; it never extracts a profile itself. Each page it reveals is rendered
to markdown the same way Tier 1 renders a page (app/scraping/render.py), and every one of those
pages — Tier 1's and Tier 2's combined — goes through the same extraction call
(app/scraping/extraction.py). Two LLM concerns, two prompts, one extraction schema.
"""

import base64
from dataclasses import dataclass
from typing import Literal

import anthropic
from playwright.async_api import Browser, Page
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.ssrf import UnsafeUrlError, assert_safe_url
from app.scraping.render import RenderedPage, content_hash, extract_markdown

MODEL = "claude-opus-5"
MAX_STEPS = 8
_NAV_TIMEOUT_MS = 15_000
_SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024


class VisualAction(BaseModel):
    """One step the agent takes, decided from a screenshot of the page as it currently is."""

    action: Literal["click", "scroll_down", "navigate", "done"]
    x: int | None = Field(default=None, description="Pixel x coordinate — required for 'click'.")
    y: int | None = Field(default=None, description="Pixel y coordinate — required for 'click'.")
    url: str | None = Field(
        default=None, description="An absolute URL visible on the page — required for 'navigate'."
    )
    reasoning: str = Field(
        description="One sentence: why this action reveals more information, or why the page is done."
    )


@dataclass(frozen=True)
class ExplorationResult:
    pages: list[RenderedPage]
    tokens_in: int
    tokens_out: int


def _prompt(step: int, max_steps: int) -> str:
    return (
        f"This is step {step + 1} of at most {max_steps} exploring a company's website to find "
        "its products, services, and competencies. Follow this priority: FIRST, if the current "
        "screenshot doesn't obviously show the bottom of the page, scroll down — a page can keep "
        "revealing more content (extra rows of a grid, more sections) well past what's visible "
        "right now, and a heading like 'Explore our portfolio' or 'Our products' specifically "
        "means a grid or list of individually-named items follows, very likely continuing further "
        "than one screen. Don't click anything on this page, or navigate away from it, until "
        "you're confident scrolling has nothing left to reveal here. ONLY once that's true should "
        "you click a tab, accordion, dropdown, or 'load more' button that only appears after "
        "interacting with the page, or a primary navigation item (e.g. 'Products', 'Innovation', "
        "'Solutions', 'Portfolio') — those are often exactly where a dedicated product or "
        "technology catalogue lives, separate from whatever the homepage already shows, so still "
        "visit them once you've exhausted the page you're on.\n\n"
        "Look at the screenshot and choose ONE action: scroll down to see more of the current "
        "page, click a specific point that looks like it would reveal more product/service/"
        "competency information, navigate to a specific visible link's URL, or 'done' once you "
        "don't expect another action to reveal anything new. Coordinates are pixels from the "
        "top-left of the screenshot you were given."
    )


async def _decide_next_action(
    screenshot_png: bytes, *, step: int, max_steps: int, api_key: str | None
) -> tuple[VisualAction, int, int]:
    """One structured-output call, given the current screenshot. Returns the action plus the
    call's own token usage, so the caller can fold it into the job's running total."""
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key or None)
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        output_config={"effort": "low"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(screenshot_png).decode(),
                        },
                    },
                    {"type": "text", "text": _prompt(step, max_steps)},
                ],
            }
        ],
        output_format=VisualAction,
    )
    if response.parsed_output is None:
        # A refusal or a truncated response — the outer loop's except clause treats this exactly
        # like any other step failure: exploration ends here with whatever was already gathered.
        raise ValueError("The model returned no parsed action.")
    return response.parsed_output, response.usage.input_tokens, response.usage.output_tokens


async def _execute(browser_page: Page, action: VisualAction) -> None:
    """Perform one action against the live page."""
    if action.action == "click" and action.x is not None and action.y is not None:
        await browser_page.mouse.click(action.x, action.y)
        await browser_page.wait_for_timeout(500)
    elif action.action == "scroll_down":
        await browser_page.mouse.wheel(0, 800)
        await browser_page.wait_for_timeout(300)
    elif action.action == "navigate" and action.url:
        assert_safe_url(action.url)  # raises UnsafeUrlError, caught by the caller's loop
        await browser_page.goto(action.url, timeout=_NAV_TIMEOUT_MS, wait_until="networkidle")


async def explore_visually(
    browser: Browser, start_url: str, *, max_steps: int = MAX_STEPS, api_key: str | None = None
) -> ExplorationResult:
    """Click around a site for up to `max_steps` steps, capturing each state it reveals as a
    `RenderedPage` (markdown plus a screenshot). Never raises — a page that errors, an unsafe
    navigate target, or an LLM call failure just ends exploration with whatever was gathered so
    far, since Tier 2 is an enhancement over Tier 1's already-successful render, not a
    replacement for it.
    """
    pages: list[RenderedPage] = []
    tokens_in = tokens_out = 0

    page = await browser.new_page(user_agent="ReScope-Scraper/1.0")
    try:
        await page.goto(start_url, timeout=_NAV_TIMEOUT_MS, wait_until="networkidle")
    except Exception:  # noqa: BLE001
        await page.close()
        return ExplorationResult(pages=pages, tokens_in=tokens_in, tokens_out=tokens_out)

    for step in range(max_steps):
        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            if len(screenshot) > _SCREENSHOT_MAX_BYTES:
                break
            action, step_tokens_in, step_tokens_out = await _decide_next_action(
                screenshot, step=step, max_steps=max_steps, api_key=api_key
            )
            tokens_in += step_tokens_in
            tokens_out += step_tokens_out

            if action.action == "done":
                break

            await _execute(page, action)

            markdown = await extract_markdown(page)
            if markdown:
                pages.append(
                    RenderedPage(
                        url=start_url,
                        final_url=page.url,
                        status_code=None,
                        markdown=markdown,
                        content_hash=content_hash(markdown),
                        screenshot=screenshot,
                    )
                )
        except UnsafeUrlError:
            break
        except Exception:  # noqa: BLE001 — one bad step ends exploration, never the whole job
            break

    await page.close()
    return ExplorationResult(pages=pages, tokens_in=tokens_in, tokens_out=tokens_out)
