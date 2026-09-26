"""Typed seam between conversation intent detection and MCP tool calls.

Only explicit, already-classified events are dispatched; full chat histories
are neither synchronized nor persisted by this interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One bounded call selected by a conversation dispatcher."""

    name: str
    arguments: Mapping[str, object]


class ConversationToolDispatcher(Protocol):
    """Contract for deterministic conversation-to-tool dispatch adapters."""

    def dispatch(
        self,
        fixture_id: str,
        *,
        context: Mapping[str, str] | None = None,
    ) -> tuple[ToolCall, ...]: ...
