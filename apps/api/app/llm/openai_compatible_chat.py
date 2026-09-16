"""One adapter for every chat provider that speaks OpenAI's chat-completions protocol — OpenAI
itself, Gemini through its own OpenAI-compatible endpoint, and Nebius, distinguished only by
`base_url` (docs/PLAN.md §16). Usage comes back on the stream's final chunk when the provider
reports it (`stream_options={"include_usage": True}`); one that doesn't leaves `usage` `None`
rather than a guessed number.
"""

from collections.abc import AsyncIterator
from typing import cast

import openai

from app.llm.base import ChatUsage


class OpenAICompatibleChat:
    def __init__(self, api_key: str, *, base_url: str) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._usage: ChatUsage | None = None

    async def stream_text(
        self, *, system: str, messages: list[dict[str, str]], model: str, max_tokens: int
    ) -> AsyncIterator[str]:
        openai_messages = cast(
            "list[openai.types.chat.ChatCompletionMessageParam]",
            [{"role": "system", "content": system}, *messages],
        )
        stream = await self._client.chat.completions.create(
            model=model,
            messages=openai_messages,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if chunk.usage is not None:
                self._usage = ChatUsage(
                    tokens_in=chunk.usage.prompt_tokens, tokens_out=chunk.usage.completion_tokens
                )
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @property
    def usage(self) -> ChatUsage | None:
        return self._usage
