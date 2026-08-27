import asyncio
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class TurnHandle:
    conversation_id: str
    record_id: int | None = None


class ConversationStore(Protocol):
    async def get(self, conversation_id: str) -> list[dict[str, Any]]: ...

    async def begin_turn(
        self,
        conversation_id: str,
        question: str,
        *,
        agent_type: str,
        fileid: str | None = None,
    ) -> TurnHandle: ...

    async def finish_turn(
        self,
        handle: TurnHandle,
        *,
        question: str,
        answer: str,
        thinking: str | None = None,
        tools: str | None = None,
        reference: str | None = None,
        recommend: str | None = None,
        first_response_time: int | None = None,
        total_response_time: int | None = None,
    ) -> None: ...

    async def update_recommendation(
        self,
        handle: TurnHandle,
        *,
        recommend: str,
        total_response_time: int | None = None,
    ) -> None: ...


class InMemoryConversationStore:
    """Infrastructure-free ChatMemory used by the default local demo."""

    def __init__(self, max_messages: int = 30) -> None:
        self._messages: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._max_messages = max_messages

    async def get(self, conversation_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            return deepcopy(self._messages[conversation_id])

    async def begin_turn(
        self,
        conversation_id: str,
        question: str,
        *,
        agent_type: str,
        fileid: str | None = None,
    ) -> TurnHandle:
        # Keep the old demo behavior: an incomplete/stopped request is not added
        # to in-memory history. Database mode persists the question immediately.
        return TurnHandle(conversation_id=conversation_id)

    async def finish_turn(
        self,
        handle: TurnHandle,
        *,
        question: str,
        answer: str,
        thinking: str | None = None,
        tools: str | None = None,
        reference: str | None = None,
        recommend: str | None = None,
        first_response_time: int | None = None,
        total_response_time: int | None = None,
    ) -> None:
        await self.append(
            handle.conversation_id,
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        )

    async def update_recommendation(
        self,
        handle: TurnHandle,
        *,
        recommend: str,
        total_response_time: int | None = None,
    ) -> None:
        return None

    async def append(self, conversation_id: str, *messages: dict[str, Any]) -> None:
        async with self._lock:
            self._messages[conversation_id].extend(deepcopy(list(messages)))
            self._messages[conversation_id] = self._messages[conversation_id][-self._max_messages :]
