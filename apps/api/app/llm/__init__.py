"""The chat provider seam (docs/PLAN.md §18) — one protocol, one Anthropic adapter, one
OpenAI-compatible adapter covering OpenAI, Gemini, and Nebius."""

from app.llm.base import ChatProvider, ChatUsage
from app.llm.factory import CHAT_PROVIDERS, OPENAI_COMPATIBLE_BASE_URLS, build_chat_provider

__all__ = [
    "CHAT_PROVIDERS",
    "OPENAI_COMPATIBLE_BASE_URLS",
    "ChatProvider",
    "ChatUsage",
    "build_chat_provider",
]
