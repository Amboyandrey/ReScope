"""The one place that knows which `ChatProvider` implementation, and which base URL, goes with
which `Provider` value (docs/PLAN.md §18, §22)."""

from app.llm.anthropic_chat import AnthropicChat
from app.llm.base import ChatProvider
from app.llm.openai_compatible_chat import OpenAICompatibleChat
from app.models import Provider

OPENAI_COMPATIBLE_BASE_URLS = {
    Provider.OPENAI: "https://api.openai.com/v1",
    Provider.GEMINI: "https://generativelanguage.googleapis.com/v1beta/openai/",
    Provider.NEBIUS: "https://api.studio.nebius.com/v1/",
}

# Providers `build_chat_provider` (and credential validation) actually know how to talk to for
# chat — deliberately excludes BROWSER_USE, which has nothing to do with chat. CUSTOM has no
# constant base URL (it comes from the workspace's own credential), so it's listed by hand rather
# than folded into OPENAI_COMPATIBLE_BASE_URLS.
CHAT_PROVIDERS = frozenset({Provider.ANTHROPIC, Provider.CUSTOM, *OPENAI_COMPATIBLE_BASE_URLS})


def build_chat_provider(provider: Provider, api_key: str, *, base_url: str | None = None) -> ChatProvider:
    """`base_url` is required for `Provider.CUSTOM` — the workspace's own server — and ignored for
    every other provider, which already has a constant one."""
    if provider == Provider.ANTHROPIC:
        return AnthropicChat(api_key)
    if provider == Provider.CUSTOM:
        if not base_url:
            raise ValueError("Provider.CUSTOM requires a base_url.")
        return OpenAICompatibleChat(api_key, base_url=base_url)
    return OpenAICompatibleChat(api_key, base_url=OPENAI_COMPATIBLE_BASE_URLS[provider])
