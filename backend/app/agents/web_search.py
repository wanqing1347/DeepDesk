import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..memory import ConversationStore, TurnHandle
from ..metrics import record_tool_call
from ..providers.llm import OpenAICompatibleClient
from ..schemas import AgentEvent
from ..streaming import ThinkTagStreamParser
from ..tools.web_search import WebSearchTool
from ..tracing import trace_tool_call

SYSTEM_PROMPT = """你是一个通用 AI 助手，负责准确、清晰、自然地回答用户的问题。
当问题需要最新信息、事实核验，或用户明确要求联网搜索时，调用 web_search 工具。
对无需最新信息的问题直接回答，不要为了使用工具而搜索，也不要把回答限制在某个行业或业务领域。
调用工具前不要编造结果；收到搜索结果后，基于来源回答，并尽量给出简洁结论。
如果当前上下文已经足够，不要重复调用相同工具。
除非用户主动询问，否则不要介绍自己的系统身份、内部实现或工具能力。
最终回答使用自然语言，不输出工具调用 JSON。"""

RECOMMEND_PROMPT = """根据用户与AI助手的对话历史，生成3个相关的推荐问题。
要求：
1. 以当前最新一轮问答为主自然延伸；
2. 每个问题简洁、具体，一般不超过20个字；
3. 三个问题不要重复，也不要与当前问题完全相同；
4. 只输出 JSON 字符串数组，不要输出 Markdown 或其他说明。
示例：["问题1","问题2","问题3"]"""


@dataclass(slots=True)
class _ToolCallBuffer:
    index: int
    call_id: str = ""
    name: str = ""
    arguments: str = ""

    def merge(self, delta: dict[str, Any]) -> None:
        call_id = delta.get("id")
        if call_id:
            self.call_id += str(call_id)
        function = delta.get("function") or {}
        name = function.get("name")
        if name:
            self.name += str(name)
        arguments = function.get("arguments")
        if arguments:
            self.arguments += str(arguments)

    def as_message_tool_call(self, round_number: int) -> dict[str, Any]:
        return {
            "id": self.call_id or f"call-{round_number}-{self.index}",
            "type": "function",
            "function": {
                "name": self.name or "unknown",
                "arguments": self.arguments or "{}",
            },
        }


@dataclass(slots=True)
class _RoundState:
    answer_parts: list[str] = field(default_factory=list)
    tool_calls: dict[int, _ToolCallBuffer] = field(default_factory=dict)

    def merge_tool_call(self, delta: dict[str, Any]) -> None:
        raw_index = delta.get("index", 0)
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = 0
        buffer = self.tool_calls.setdefault(index, _ToolCallBuffer(index=index))
        buffer.merge(delta)

    def completed_tool_calls(self, round_number: int) -> list[dict[str, Any]]:
        return [self.tool_calls[index].as_message_tool_call(round_number) for index in sorted(self.tool_calls)]


class WebSearchAgent:
    def __init__(
        self,
        settings: Settings,
        memory: ConversationStore,
        *,
        llm_client: OpenAICompatibleClient | None = None,
        search_tool: WebSearchTool | None = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._llm = llm_client or OpenAICompatibleClient(settings)
        self._search = search_tool or WebSearchTool(settings)

    async def run(self, conversation_id: str, question: str) -> AsyncIterator[AgentEvent]:
        started_at = time.perf_counter()
        history = await self._memory.get(conversation_id)
        turn_handle = await self._memory.begin_turn(
            conversation_id,
            question,
            agent_type="websearch",
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
        messages.append({"role": "user", "content": question})
        references: list[dict[str, Any]] = []
        thinking_parts: list[str] = []
        used_tools: set[str] = set()

        initial_thinking = "正在分析问题...\n"
        thinking_parts.append(initial_thinking)
        first_response_time = int((time.perf_counter() - started_at) * 1000)
        yield AgentEvent(type="thinking", content=initial_thinking)

        for round_number in range(1, self._settings.max_agent_rounds + 1):
            state = _RoundState()
            async for event in self._stream_model(messages, [self._search.definition], state):
                if event.type == "thinking" and event.content:
                    thinking_parts.append(str(event.content))
                yield event

            tool_calls = state.completed_tool_calls(round_number)
            if not tool_calls:
                answer = "".join(state.answer_parts)
                async for event in self._finish_answer(
                    turn_handle,
                    history,
                    question,
                    answer,
                    references,
                    thinking_parts,
                    used_tools,
                    first_response_time,
                    started_at,
                ):
                    yield event
                return

            messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            round_thinking = f"第 {round_number} 轮：正在检索相关信息...\n"
            thinking_parts.append(round_thinking)
            yield AgentEvent(type="thinking", content=round_thinking)

            for tool_call in tool_calls:
                function = tool_call["function"]
                arguments = str(function.get("arguments") or "{}")
                query = self._extract_query(arguments)
                if query:
                    search_thinking = f"🔍 正在搜索信息: {query}\n"
                    thinking_parts.append(search_thinking)
                    yield AgentEvent(type="thinking", content=search_thinking)
                yield AgentEvent.tool_start(str(function.get("name") or "unknown"), str(tool_call["id"]), arguments)

            results = await asyncio.gather(*(self._execute_tool_call(tool_call) for tool_call in tool_calls))

            # asyncio.gather preserves the input ordering.
            # implementation, which executes tool calls concurrently but appends
            # ToolResponse objects back to the model in original call order.
            for tool_call, (_, serialized_result, tool_references, invoked) in zip(
                tool_calls,
                results,
                strict=True,
            ):
                function = tool_call["function"]
                tool_name = str(function.get("name") or "unknown")
                call_id = str(tool_call["id"])
                references.extend(tool_references)
                if invoked:
                    used_tools.add(tool_name)
                yield AgentEvent.tool_end(tool_name, call_id, serialized_result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": serialized_result,
                    }
                )

        # After the tool round limit, make
        # one final streaming model call with tools disabled.
        force_thinking = "已达到最大推理轮次，正在基于已有信息生成最终答案...\n"
        thinking_parts.append(force_thinking)
        yield AgentEvent(type="thinking", content=force_thinking)
        force_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "你已达到最大推理轮次限制。请基于当前已有信息直接给出最终答案，"
                    "禁止继续调用工具；信息不足时请明确说明。"
                ),
            },
        ]
        state = _RoundState()
        async for event in self._stream_model(force_messages, [], state):
            if event.type == "thinking" and event.content:
                thinking_parts.append(str(event.content))
            yield event
        answer = "".join(state.answer_parts)
        async for event in self._finish_answer(
            turn_handle,
            history,
            question,
            answer,
            references,
            thinking_parts,
            used_tools,
            first_response_time,
            started_at,
        ):
            yield event

    async def _stream_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        state: _RoundState,
    ) -> AsyncIterator[AgentEvent]:
        parser = ThinkTagStreamParser()
        async for delta in self._llm.stream_chat(messages, tools):
            reasoning = delta.get("reasoning_content")
            if reasoning:
                yield AgentEvent(type="thinking", content=str(reasoning))

            for tool_call_delta in delta.get("tool_calls") or []:
                if isinstance(tool_call_delta, dict):
                    state.merge_tool_call(tool_call_delta)

            content = delta.get("content")
            if content:
                for segment in parser.feed(str(content)):
                    if segment.thinking:
                        yield AgentEvent(type="thinking", content=segment.content)
                    else:
                        state.answer_parts.append(segment.content)
                        yield AgentEvent(type="text", content=segment.content)

        for segment in parser.finish():
            if segment.thinking:
                yield AgentEvent(type="thinking", content=segment.content)
            else:
                state.answer_parts.append(segment.content)
                yield AgentEvent(type="text", content=segment.content)

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
    ) -> tuple[Any, str, list[dict[str, Any]], bool]:
        function = tool_call.get("function") or {}
        tool_name = str(function.get("name") or "unknown")
        arguments = str(function.get("arguments") or "{}")
        references: list[dict[str, Any]] = []
        invoked = False
        tool_started_at = time.perf_counter()

        try:
            if tool_name != self._search.name:
                tool_result: Any = {"error": f"工具未找到：{tool_name}"}
            else:
                with trace_tool_call(tool_name):
                    tool_result = await self._search.call(arguments)
                invoked = True
                if isinstance(tool_result, dict):
                    search_results = tool_result.get("results") or []
                    if isinstance(search_results, list):
                        references = [item for item in search_results if isinstance(item, dict) and item.get("url")]
        except Exception as exc:
            tool_result = {"error": f"工具执行失败：{exc}"}
        finally:
            record_tool_call(
                tool_name,
                started_at=tool_started_at,
                outcome="success" if invoked else "error",
            )

        serialized_result = json.dumps(tool_result, ensure_ascii=False)
        return tool_result, serialized_result, references, invoked

    async def _finish_answer(
        self,
        turn_handle: TurnHandle,
        history: list[dict[str, Any]],
        question: str,
        answer: str,
        references: list[dict[str, Any]],
        thinking_parts: list[str],
        used_tools: set[str],
        first_response_time: int,
        started_at: float,
    ) -> AsyncIterator[AgentEvent]:
        if not answer.strip():
            raise RuntimeError("模型未返回最终答案")

        reference_storage: str | None = None
        if references:
            reference_content = json.dumps(references, ensure_ascii=False)
            reference_storage = json.dumps(
                {
                    "type": "reference",
                    "content": reference_content,
                    "count": len(references),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield AgentEvent(type="reference", content=references, count=len(references))

        # Every answer token has reached the SSE generator before this method is
        # entered. Persist the core turn now so stopping during the optional
        # recommendation call cannot lose an answer the user already received.
        total_response_time = int((time.perf_counter() - started_at) * 1000)
        await self._memory.finish_turn(
            turn_handle,
            question=question,
            answer=answer,
            thinking="".join(thinking_parts) or None,
            tools=",".join(sorted(used_tools)),
            reference=reference_storage,
            first_response_time=first_response_time,
            total_response_time=total_response_time,
        )

        if self._settings.enable_recommendations:
            recommendations = await self._generate_recommendations(history, question, answer)
            if recommendations:
                recommend_storage = json.dumps(recommendations, ensure_ascii=False)
                total_response_time = int((time.perf_counter() - started_at) * 1000)
                await self._memory.update_recommendation(
                    turn_handle,
                    recommend=recommend_storage,
                    total_response_time=total_response_time,
                )
                yield AgentEvent(type="recommend", content=recommendations, count=len(recommendations))

        yield AgentEvent.complete()

    async def _generate_recommendations(
        self,
        history: list[dict[str, Any]],
        question: str,
        answer: str,
    ) -> list[str]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": RECOMMEND_PROMPT},
            *history,
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": "请生成3个推荐问题，只输出 JSON 字符串数组。"},
        ]
        try:
            response = await self._llm.complete(messages, [])
            raw = str(response.get("choices", [{}])[0].get("message", {}).get("content") or "")
            return self._parse_recommendations(raw)
        except Exception:
            # Recommendation generation is best-effort
            # as well; a secondary LLM failure must not turn a valid answer into an error.
            return []

    @staticmethod
    def _parse_recommendations(raw: str) -> list[str]:
        text = raw.strip()
        if not text:
            return []
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < start:
            return []
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []

        recommendations: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if normalized and normalized not in recommendations:
                recommendations.append(normalized)
            if len(recommendations) == 3:
                break
        return recommendations

    @staticmethod
    def _extract_query(arguments: str) -> str:
        try:
            value = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return ""
        if not isinstance(value, dict):
            return ""
        return str(value.get("query") or "").strip()
