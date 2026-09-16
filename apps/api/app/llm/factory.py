"""The one place that knows which `ChatProvider` implementation, and which base URL, goes with
which `Provider` value (docs/PLAN.md §18)."""

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
# chat — deliberately excludes BROWSER_USE, which has nothing to do with chat.
CHAT_PROVIDERS = frozenset({Provider.ANTHROPIC, *OPENAI_COMPATIBLE_BASE_URLS})


def build_chat_provider(provider: Provider, api_key: str) -> ChatProvider:
    if provider == Provider.ANTHROPIC:
        return AnthropicChat(api_key)
    return OpenAICompatibleChat(api_key, base_url=OPENAI_COMPATIBLE_BASE_URLS[provider])
