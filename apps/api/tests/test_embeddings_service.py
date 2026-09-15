"""The TEI client — batching and pass-through, against a fake transport so no real service (or
its absence) affects the result."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.services.embeddings import embed_text, embed_texts

# Captured once, before any test patches `httpx.AsyncClient` — every fake client below is built
# from this real reference so patches never accidentally stack on top of an earlier test's fake.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install_fake_tei(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Route every httpx.AsyncClient the embeddings service creates through `handler` instead of
    the real network — same fake-transport seam app/scraping/discovery.py's own tests use."""

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


def _echo_handler(request: httpx.Request) -> httpx.Response:
    """One vector per input, each `[batch-position]` so the response shape is easy to assert on."""
    inputs = json.loads(request.content)["inputs"]
    return httpx.Response(200, json=[[float(i)] for i in range(len(inputs))])


async def test_empty_input_makes_no_request() -> None:
    assert await embed_texts([]) == []


async def test_single_text_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_tei(monkeypatch, _echo_handler)
    vectors = await embed_texts(["hello"])
    assert vectors == [[0.0]]


async def test_embed_text_returns_one_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_tei(monkeypatch, _echo_handler)
    assert await embed_text("hello") == [0.0]


async def test_batches_respect_the_backend_concurrency_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        seen_batch_sizes.append(len(inputs))
        return httpx.Response(200, json=[[0.0] for _ in inputs])

    _install_fake_tei(monkeypatch, handler)

    texts = [f"text-{i}" for i in range(10)]
    vectors = await embed_texts(texts)

    assert len(vectors) == 10
    assert seen_batch_sizes == [4, 4, 2]
