"""Browser Use Cloud as a second Tier 2 provider (docs/PLAN.md §13) — plain HTTP against their
hosted API, not the `browser-use` library, which hard-pins `anthropic==0.76.0` against the
`anthropic>=1.5.0` app/scraping/extraction.py needs (the same conflict app/scraping/visual_agent.py's
own docstring explains for the custom agent).

Unlike the custom agent, this provider does its own extraction on Browser Use's own
infrastructure and model — it hands back a complete `ExtractedProfile` directly (via
`structuredOutput`), not raw pages for our own extraction call to run on. `app/scraping/merge.py`
combines that profile with Tier 1's own.
"""

import asyncio
import json
from dataclasses import dataclass

import httpx

from app.scraping.extraction import ExtractedProfile
from app.scraping.render import RenderedPage, content_hash

BASE_URL = "https://api.browser-use.com/api/v2"
# One of Browser Use's own hosted models (see CLOUD.md) — their own infrastructure runs it, not
# ours, so this isn't the Anthropic key resolved for the rest of the pipeline.
MODEL = "browser-use-llm"
MAX_STEPS = 30
POLL_INTERVAL_SECONDS = 5.0
MAX_WAIT_SECONDS = 600  # a hard 10-minute ceiling — a client timeout never cancels the remote run

_TASK_PROMPT = (
    "Explore this company's own website thoroughly, including any content behind tabs, "
    "accordions, menus, or 'load more' buttons. Extract its overview, the company facts in the "
    "given schema (country as an ISO 3166-1 alpha-2 code, city, industry, company type, employee "
    "range, founded year, social links) — leave a fact null rather than guess if the site doesn't "
    "actually state it — the products and services it offers, and its competencies (capabilities, "
    "technologies, certifications, industries served, partnerships). Only include what the site "
    "actually supports — do not invent offerings or competencies. Every offering and competency "
    "needs a real description and at least one evidence entry citing the page URL and a "
    "supporting quote. Omit an offering or competency entirely rather than include it without a "
    "real description."
)


class BrowserUseTaskFailed(Exception):
    """The task never reached a usable result — timed out, was stopped, or returned no output.
    Caught by the pipeline exactly like a custom Tier 2 failure: deep mode degrades to whatever
    Tier 0 + Tier 1 already found, it never fails the whole job."""


@dataclass(frozen=True)
class BrowserUseResult:
    profile: ExtractedProfile | None
    pages: list[RenderedPage]
    steps: int


async def run_browser_use_task(*, api_key: str, website_url: str, domain: str) -> BrowserUseResult:
    """Submit a profiling task, poll it to completion, and return the profile it extracted plus
    each step's screenshot as evidence. Raises `BrowserUseTaskFailed` on any failure — the caller
    decides what "deep mode came up empty" means for the rest of the job."""
    headers = {"X-Browser-Use-API-Key": api_key}
    schema = json.dumps(ExtractedProfile.model_json_schema())

    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=30.0) as client:
        try:
            create_response = await client.post(
                "/tasks",
                json={
                    "task": _TASK_PROMPT,
                    "llm": MODEL,
                    "startUrl": website_url,
                    "maxSteps": MAX_STEPS,
                    "structuredOutput": schema,
                    "allowedDomains": [domain],
                },
            )
            create_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BrowserUseTaskFailed(f"Could not create the Browser Use task: {exc}") from exc

        task_id = create_response.json()["id"]
        task_data = await _poll_until_done(client, task_id)

        if task_data.get("status") != "finished":
            raise BrowserUseTaskFailed(f"Browser Use task {task_id} ended as {task_data.get('status')!r}.")

        output = task_data.get("output")
        if not isinstance(output, str) or not output:
            raise BrowserUseTaskFailed(f"Browser Use task {task_id} finished with no output.")

        try:
            profile = ExtractedProfile.model_validate_json(output)
        except ValueError as exc:
            raise BrowserUseTaskFailed(
                f"Browser Use task {task_id}'s output didn't match the schema: {exc}"
            ) from exc

        pages = await _download_screenshot_pages(client, task_data, website_url)

    steps = task_data.get("steps")
    step_count = len(steps) if isinstance(steps, list) else 0
    return BrowserUseResult(profile=profile, pages=pages, steps=step_count)


async def _poll_until_done(client: httpx.AsyncClient, task_id: str) -> dict[str, object]:
    elapsed = 0.0
    while elapsed < MAX_WAIT_SECONDS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        try:
            status_response = await client.get(f"/tasks/{task_id}")
            status_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BrowserUseTaskFailed(f"Could not poll Browser Use task {task_id}: {exc}") from exc
        task_data: dict[str, object] = status_response.json()
        if task_data.get("status") in ("finished", "stopped"):
            return task_data
    raise BrowserUseTaskFailed(f"Browser Use task {task_id} did not finish within {MAX_WAIT_SECONDS}s.")


async def _download_screenshot_pages(
    client: httpx.AsyncClient, task_data: dict[str, object], website_url: str
) -> list[RenderedPage]:
    """Each step's screenshot, downloaded and kept as evidence the same way the custom agent's
    own screenshots are — never fed into our own extraction, since Browser Use already did its
    own. A step whose image fails to download is skipped rather than failing the whole task."""
    steps = task_data.get("steps")
    if not isinstance(steps, list):
        return []
    pages: list[RenderedPage] = []
    for step in steps:
        if not isinstance(step, dict) or not step.get("screenshotUrl"):
            continue
        try:
            image_response = await client.get(str(step["screenshotUrl"]))
            image_response.raise_for_status()
        except httpx.HTTPError:
            continue
        url = str(step.get("url") or website_url)
        pages.append(
            RenderedPage(
                url=url,
                final_url=url,
                status_code=None,
                markdown="",
                content_hash=content_hash(str(step["screenshotUrl"])),
                screenshot=image_response.content,
            )
        )
    return pages
