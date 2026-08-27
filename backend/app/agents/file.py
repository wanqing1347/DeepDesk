import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..config import Settings
from ..memory import ConversationStore, TurnHandle
from ..metrics import record_tool_call
from ..providers.llm import OpenAICompatibleClient
from ..schemas import AgentEvent
from ..streaming import ThinkTagStreamParser
from ..tools.file_content import FileContentTool
from ..tracing import trace_tool_call

RECOMMEND_PROMPT = """根据用户与AI助手的对话历史，生成3个相关的推荐问题。
要求：
1. 以当前最新一轮文件问答为主自然延伸；
2. 每个问题简洁、具体，一般不超过20个字；
3. 三个问题不要重复，也不要与当前问题完全相同；
4. 只输出 JSON 字符串数组，不要输出 Markdown 或其他说明。"""


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
        self.tool_calls.setdefault(index, _ToolCallBuffer(index=index)).merge(delta)

    def completed_tool_calls(self, round_number: int) -> list[dict[str, Any]]:
        return [self.tool_calls[index].as_message_tool_call(round_number) for index in sorted(self.tool_calls)]


class FileAgent:
    def __init__(
        self,
        settings: Settings,
        memory: ConversationStore,
        file_content_tool: FileContentTool,
        *,
        llm_client: OpenAICompatibleClient | None = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._llm = llm_client or OpenAICompatibleClient(settings)
        self._tool = file_content_tool

    async def run(self, conversation_id: str, question: str, file_id: str) -> AsyncIterator[AgentEvent]:
        started_at = time.perf_counter()
        history = await self._memory.get(conversation_id)
        turn_handle = await self._memory.begin_turn(
            conversation_id,
            question,
            agent_type="file",
            fileid=file_id,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            *history,
            {"role": "user", "content": f"<question>{question}</question>"},
            {"role": "user", "content": f"<fileid>{file_id}</fileid>"},
        ]
        thinking_parts: list[str] = []
        used_tools: set[str] = set()

        initial_thinking = "正在分析文件问题...\n"
        thinking_parts.append(initial_thinking)
        first_response_time = int((time.perf_counter() - started_at) * 1000)
        yield AgentEvent(type="thinking", content=initial_thinking)

        for round_number in range(1, self._settings.max_agent_rounds + 1):
            state = _RoundState()
            async for event in self._stream_model(messages, [self._tool.definition], state):
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
                    thinking_parts,
                    used_tools,
                    first_response_time,
                    started_at,
                ):
                    yield event
                return

            messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            for tool_call in tool_calls:
                function = tool_call["function"]
                tool_name = str(function.get("name") or "unknown")
                arguments = str(function.get("arguments") or "{}")
                if tool_name == self._tool.name:
                    load_thinking = "📂 正在检索文件内容，请稍等...\n"
                    thinking_parts.append(load_thinking)
                    yield AgentEvent(type="thinking", content=load_thinking)
                yield AgentEvent.tool_start(tool_name, str(tool_call["id"]), arguments)

            results = await asyncio.gather(*(self._execute_tool_call(tool_call) for tool_call in tool_calls))
            for tool_call, (serialized_result, invoked) in zip(tool_calls, results, strict=True):
                function = tool_call["function"]
                tool_name = str(function.get("name") or "unknown")
                call_id = str(tool_call["id"])
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

        force_thinking = "已达到最大推理轮次，正在基于已有文件内容生成最终答案...\n"
        thinking_parts.append(force_thinking)
        yield AgentEvent(type="thinking", content=force_thinking)
        force_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "你已达到最大推理轮次限制。请基于已经获取的文件内容直接给出最终答案，"
                    "禁止继续调用工具；文件信息不足时请明确说明。"
                ),
            },
        ]
        state = _RoundState()
        async for event in self._stream_model(force_messages, [], state):
            if event.type == "thinking" and event.content:
                thinking_parts.append(str(event.content))
            yield event
        async for event in self._finish_answer(
            turn_handle,
            history,
            question,
            "".join(state.answer_parts),
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

    async def _execute_tool_call(self, tool_call: dict[str, Any]) -> tuple[str, bool]:
        function = tool_call.get("function") or {}
        tool_name = str(function.get("name") or "unknown")
        arguments = str(function.get("arguments") or "{}")
        tool_started_at = time.perf_counter()
        invoked = False
        try:
            if tool_name != self._tool.name:
                return json.dumps({"error": f"工具未找到：{tool_name}"}, ensure_ascii=False), False
            with trace_tool_call(tool_name):
                result = await self._tool.call(arguments)
            invoked = True
            return result, True
        except Exception as exc:
            return json.dumps({"error": f"工具执行失败：{exc}"}, ensure_ascii=False), False
        finally:
            record_tool_call(
                tool_name,
                started_at=tool_started_at,
                outcome="success" if invoked else "error",
            )

    async def _finish_answer(
        self,
        turn_handle: TurnHandle,
        history: list[dict[str, Any]],
        question: str,
        answer: str,
        thinking_parts: list[str],
        used_tools: set[str],
        first_response_time: int,
        started_at: float,
    ) -> AsyncIterator[AgentEvent]:
        if not answer.strip():
            raise RuntimeError("模型未返回最终答案")

        total_response_time = int((time.perf_counter() - started_at) * 1000)
        await self._memory.finish_turn(
            turn_handle,
            question=question,
            answer=answer,
            thinking="".join(thinking_parts) or None,
            tools=",".join(sorted(used_tools)),
            first_response_time=first_response_time,
            total_response_time=total_response_time,
        )

        if self._settings.enable_recommendations:
            recommendations = await self._generate_recommendations(history, question, answer)
            if recommendations:
                total_response_time = int((time.perf_counter() - started_at) * 1000)
                await self._memory.update_recommendation(
                    turn_handle,
                    recommend=json.dumps(recommendations, ensure_ascii=False),
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
            return []

    @staticmethod
    def _parse_recommendations(raw: str) -> list[str]:
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end < start:
            return []
        try:
            value = json.loads(raw[start : end + 1])
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
    def _system_prompt() -> str:
        return f"""## 角色
你是 DeepDesk 的专业文件分析助手，帮助用户理解和分析上传的文件内容。

## 当前系统时间：
{datetime.now().isoformat(sep=' ', timespec='seconds')}

## 文件处理规则
1. 你的回答必须基于当前文件的内容，禁止编造信息。
2. 文件的具体内容请必须调用loadContent工具来获取。

## 回答规范
1. 回答必须基于文件内容，禁止编造信息。
2. 可以引用文件中的具体内容、段落、数据或图表信息。
3. 文件内容不足时，诚实说明并给出可能原因。
4. 图片内容根据视觉信息进行描述分析。

## 输出规范
1. 尽可能使用 emoji 表情，让回答更友好。
2. 使用结构化方式呈现信息，章节有条理。
3. 对关键内容进行强调说明。
4. 保持回答清晰、易读。
5. 必须尽可能围绕用户提供的附件回答。
6. 禁止在回答中透露文件id、fileid。

## 最终答案规则
1. 当上下文已有全部信息时，不要再调用工具。
2. 输出最终自然语言答案，禁止包含工具调用格式。
3. 禁止重复调用同一个工具，除非失败。
"""
