"""The Browser Use Cloud client — task creation, polling, and turning the result into an
ExtractedProfile plus screenshot evidence, against a fake transport (no real API, no real key)."""

import json

import httpx
import pytest

from app.scraping import browser_use_cloud
from app.scraping.browser_use_cloud import BrowserUseTaskFailed, run_browser_use_task
from app.scraping.extraction import ExtractedEvidence, ExtractedOffering, ExtractedProfile

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _speed_up_polling(monkeypatch: pytest.MonkeyPatch, *, poll_interval: float = 0.001) -> None:
    monkeypatch.setattr(browser_use_cloud, "POLL_INTERVAL_SECONDS", poll_interval)


def _profile_json() -> str:
    profile = ExtractedProfile(
        overview="Acme makes widgets.",
        offerings=[
            ExtractedOffering(
                kind="product",
                name="Widget",
                description="A sturdy widget.",
                category=None,
                evidence=[ExtractedEvidence(url="https://acme.example/products", quote="widgets")],
            )
        ],
        competencies=[],
    )
    return profile.model_dump_json()


async def test_successful_task_returns_profile_and_screenshots(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_polling(monkeypatch)
    calls = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/tasks" and request.method == "POST":
            return httpx.Response(200, json={"id": "task-1", "sessionId": "session-1"})
        if request.url.path == "/api/v2/tasks/task-1":
            calls["status"] += 1
            if calls["status"] < 2:
                return httpx.Response(200, json={"status": "started", "steps": []})
            return httpx.Response(
                200,
                json={
                    "status": "finished",
                    "output": _profile_json(),
                    "steps": [
                        {
                            "url": "https://acme.example/products",
                            "screenshotUrl": "https://cdn.example/1.png",
                        }
                    ],
                },
            )
        if request.url == "https://cdn.example/1.png":
            return httpx.Response(200, content=b"fake-png-bytes")
        return httpx.Response(404)

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    result = await run_browser_use_task(
        api_key="bu-test-key", website_url="https://acme.example", domain="acme.example"
    )

    assert result.profile is not None
    assert result.profile.overview == "Acme makes widgets."
    assert [o.name for o in result.profile.offerings] == ["Widget"]
    assert result.steps == 1
    [page] = result.pages
    assert page.screenshot == b"fake-png-bytes"
    assert page.url == "https://acme.example/products"


async def test_stopped_task_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_polling(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/tasks" and request.method == "POST":
            return httpx.Response(200, json={"id": "task-1", "sessionId": "session-1"})
        return httpx.Response(200, json={"status": "stopped", "steps": []})

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    with pytest.raises(BrowserUseTaskFailed):
        await run_browser_use_task(
            api_key="bu-test-key", website_url="https://acme.example", domain="acme.example"
        )


async def test_task_that_never_finishes_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_polling(monkeypatch)
    monkeypatch.setattr(browser_use_cloud, "MAX_WAIT_SECONDS", 0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/tasks" and request.method == "POST":
            return httpx.Response(200, json={"id": "task-1", "sessionId": "session-1"})
        return httpx.Response(200, json={"status": "started", "steps": []})

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    with pytest.raises(BrowserUseTaskFailed):
        await run_browser_use_task(
            api_key="bu-test-key", website_url="https://acme.example", domain="acme.example"
        )


async def test_output_that_does_not_match_the_schema_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_polling(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/tasks" and request.method == "POST":
            return httpx.Response(200, json={"id": "task-1", "sessionId": "session-1"})
        return httpx.Response(
            200, json={"status": "finished", "output": json.dumps({"nonsense": True}), "steps": []}
        )

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    with pytest.raises(BrowserUseTaskFailed):
        await run_browser_use_task(
            api_key="bu-test-key", website_url="https://acme.example", domain="acme.example"
        )


async def test_no_output_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_polling(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/tasks" and request.method == "POST":
            return httpx.Response(200, json={"id": "task-1", "sessionId": "session-1"})
        return httpx.Response(200, json={"status": "finished", "output": None, "steps": []})

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    with pytest.raises(BrowserUseTaskFailed):
        await run_browser_use_task(
            api_key="bu-test-key", website_url="https://acme.example", domain="acme.example"
        )
