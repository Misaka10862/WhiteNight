"""Optional exact token counting backed by a local tokenizer.json."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from whitenight.models.base import ProviderMessage, ToolSpec


class TokenCounter(Protocol):
    @property
    def available(self) -> bool: ...

    def count_text(self, text: str) -> int | None: ...

    def count_request(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> int | None: ...


class UnavailableTokenCounter:
    @property
    def available(self) -> bool:
        return False

    def count_text(self, text: str) -> int | None:
        del text
        return None

    def count_request(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> int | None:
        del messages, tools
        return None


class JsonTokenCounter:
    """Counts tokenizer tokens; chat framing uses a documented four-token/message reserve."""

    def __init__(self, path: Path) -> None:
        from tokenizers import Tokenizer

        self.path = path.expanduser().resolve()
        self._tokenizer = Tokenizer.from_file(str(self.path))

    @property
    def available(self) -> bool:
        return True

    def count_text(self, text: str) -> int:
        return len(self._tokenizer.encode(text).ids)

    def count_request(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> int:
        total = 3
        for message in messages:
            total += 4 + self.count_text(message.role) + self.count_text(message.content)
            total += sum(1100 for _ in message.images)
            for call in message.tool_calls:
                total += self.count_text(call.model_dump_json())
        for tool in tools or []:
            total += self.count_text(tool.model_dump_json())
        return total


def build_token_counter(path: Path | None) -> TokenCounter:
    if path is None or not path.expanduser().is_file():
        return UnavailableTokenCounter()
    return JsonTokenCounter(path)
