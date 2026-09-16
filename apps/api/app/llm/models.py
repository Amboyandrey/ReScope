"""Listing a provider's own models, and narrowing that list to plausible chat models
(docs/PLAN.md §23). The denylist is deliberate, not an allowlist — a provider's new chat model
should show up here without a code change; only known-non-chat families are dropped.
"""

import anthropic
import openai

from app.core.errors import CredentialValidationFailed
from app.llm.factory import OPENAI_COMPATIBLE_BASE_URLS
from app.models import Provider

_DENYLISTS: dict[Provider, tuple[str, ...]] = {
    Provider.OPENAI: (
        "embedding",
        "whisper",
        "tts",
        "dall-e",
        "moderation",
        "davinci",
        "babbage",
        "audio",
        "realtime",
        "transcribe",
    ),
    Provider.GEMINI: ("embedding", "aqa", "imagen", "veo"),
    Provider.NEBIUS: ("embed",),
}


def filter_chat_models(provider: Provider, model_ids: list[str]) -> list[str]:
    """Drop ids matching `provider`'s denylist (case-insensitive substring match), sorted. A
    provider with no denylist here — Anthropic, or a workspace's own `CUSTOM` server whose naming
    this app can't assume anything about — keeps every id it reports."""
    denylist = _DENYLISTS.get(provider, ())
    kept = [model_id for model_id in model_ids if not any(term in model_id.lower() for term in denylist)]
    return sorted(kept)


async def list_provider_models(provider: Provider, api_key: str, *, base_url: str | None = None) -> list[str]:
    """The raw model ids `provider` reports for this key — unfiltered; `filter_chat_models`
    narrows them. Raised errors are the provider's own, surfaced verbatim. `base_url` is only
    meaningful for `Provider.CUSTOM`."""
    if provider == Provider.ANTHROPIC:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            return [model.id async for model in client.models.list()]
        except anthropic.APIStatusError as exc:
            raise CredentialValidationFailed(f"Anthropic rejected this key: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise CredentialValidationFailed("Could not reach Anthropic to list models.") from exc

    resolved_base_url = base_url if provider == Provider.CUSTOM else OPENAI_COMPATIBLE_BASE_URLS[provider]
    openai_client = openai.AsyncOpenAI(api_key=api_key, base_url=resolved_base_url)
    try:
        return [model.id async for model in openai_client.models.list()]
    except openai.APIStatusError as exc:
        raise CredentialValidationFailed(
            f"{provider.value.title()} rejected this key: {exc.message}"
        ) from exc
    except openai.APIConnectionError as exc:
        raise CredentialValidationFailed(f"Could not reach {provider.value.title()} to list models.") from exc
