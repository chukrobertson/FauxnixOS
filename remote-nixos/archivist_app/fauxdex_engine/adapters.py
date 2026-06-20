from __future__ import annotations

from typing import Protocol


class ModelChat(Protocol):
    def __call__(self, messages: list[dict], *, task: str, fallback_task: str | None = None) -> str:
        ...


class EnsureConversation(Protocol):
    def __call__(self, conversation_id: str | None, title: str) -> str:
        ...


class AddMessage(Protocol):
    def __call__(self, conversation_id: str, role: str, content: str) -> int:
        ...
