"""The provider seam chat runs behind (docs/PLAN.md §18) — one protocol, so the chat router
never imports a provider's SDK directly and a future fifth provider never touches it."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatUsage:
    tokens_in: int
    tokens_out: int


class ChatProvider(Protocol):
    """One streamed chat call. `usage` is only meaningful once the generator `stream_text`
    returns has been fully consumed — a provider reports its token counts on the stream's own
    final chunk or message, never before, and `None` if it never reports them at all."""

    def stream_text(
        self, *, system: str, messages: list[dict[str, str]], model: str, max_tokens: int
    ) -> AsyncIterator[str]: ...

    @property
    def usage(self) -> ChatUsage | None: ...
