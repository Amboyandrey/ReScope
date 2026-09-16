"""Anthropic's own SDK, streamed — the platform's default chat provider, and the only one
extraction and the visual agent ever use regardless of a workspace's own chat choice (their
structured-output and vision needs aren't portable across the other providers, docs/PLAN.md §16).
"""

from collections.abc import AsyncIterator
from typing import cast

import anthropic

from app.llm.base import ChatUsage


class AnthropicChat:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._usage: ChatUsage | None = None

    async def stream_text(
        self, *, system: str, messages: list[dict[str, str]], model: str, max_tokens: int
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=cast("list[anthropic.types.MessageParam]", messages),
        ) as message_stream:
            async for text in message_stream.text_stream:
                yield text
            final = await message_stream.get_final_message()
            self._usage = ChatUsage(tokens_in=final.usage.input_tokens, tokens_out=final.usage.output_tokens)

    @property
    def usage(self) -> ChatUsage | None:
        return self._usage
