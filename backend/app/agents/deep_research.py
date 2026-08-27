import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Settings
from ..memory import ConversationStore, TurnHandle
from ..metrics import record_tool_call
from ..providers.llm import OpenAICompatibleClient
from ..schemas import AgentEvent
from ..streaming import ThinkTagStreamParser
from ..tools.web_search import WebSearchTool
from ..tracing import trace_tool_call


@dataclass(slots=True, frozen=True)
class PlanTask:
    id: str | None
    instruction: str
    order: int


@dataclass(slots=True, frozen=True)
class TaskResult:
    task_id: str
    success: bool
    output: str | None = None
    error: str | None = None


@dataclass(slots=True, frozen=True)
class CritiqueResult:
    passed: bool
    feedback: str


@dataclass(slots=True)
class DeepResearchState:
    conversation_id: str
    question: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    round: int = 0
    refined_research_topic: str | None = None

    def next_round(self) -> None:
        self.round += 1

    def current_chars(self) -> int:
        return sum(len(str(message.get("content") or "")) for message in self.messages)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def render_full_context(self) -> str:
        last_critique = -1
        for index in range(len(self.messages) - 1, -1, -1):
            if "【Critique Feedback】" in str(self.messages[index].get("content") or ""):
                last_critique = index
                break

        rows: list[str] = []
        for index, message in enumerate(self.messages):
            content = str(message.get("content") or "")
            if index < last_critique and "【Critique Feedback】" in content:
                continue
            rows.append(f"\n\n[{str(message.get('role') or 'unknown').upper()}]\n\n{content}")
        return "".join(rows)

    def extract_tool_results(self) -> str:
        return "\n\n".join(
            str(message.get("content") or "")
            for message in self.messages
            if "【Completed Task Result】" in str(message.get("content") or "")
        )


@dataclass(slots=True)
class _CapturedStream:
    text: str = ""


@dataclass(slots=True)
class _TaskExecution:
    result: TaskResult
    references: list[dict[str, Any]] = field(default_factory=list)
    used_tools: set[str] = field(default_factory=set)
    attempts: int = 1


class DeepResearchAgent:
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
        self._tool_semaphore = asyncio.Semaphore(settings.deep_tool_concurrency)

    async def run(self, conversation_id: str, question: str) -> AsyncIterator[AgentEvent]:
        started_at = time.perf_counter()
        history = await self._memory.get(conversation_id)
        turn_handle = await self._memory.begin_turn(
            conversation_id,
            question,
            agent_type="plan-execute",
        )
        state = DeepResearchState(conversation_id=conversation_id, question=question, messages=[*history])
        state.add("user", question)
        thinking_parts: list[str] = []
        references: list[dict[str, Any]] = []
        used_tools: set[str] = set()

        first = "\n🔍 正在分析您的需求...\n"
        thinking_parts.append(first)
        first_response_time = int((time.perf_counter() - started_at) * 1000)
        yield AgentEvent(type="thinking", content=first)

        clarification = _CapturedStream()
        clarify_messages = [
            {"role": "system", "content": self._time_context() + "\n\n" + REQUIREMENT_CLARIFICATION},
            *state.messages,
        ]
        async for event in self._stream_as_thinking(clarify_messages, clarification):
            if event.content:
                thinking_parts.append(str(event.content))
            yield event

        done = "\n✅ 需求分析完成\n"
        thinking_parts.append(done)
        yield AgentEvent(type="thinking", content=done)
        if "【需要补充信息】" in clarification.text:
            pause_answer = "⏸【暂停深入研究】" + clarification.text.replace("【需要补充信息】", "").strip()
            yield AgentEvent(type="text", content=pause_answer)
            await self._finish_turn(
                turn_handle,
                question,
                pause_answer,
                thinking_parts,
                used_tools,
                references,
                first_response_time,
                started_at,
            )
            yield AgentEvent.complete()
            return

        ready = "✅ 信息充足，准备生成研究主题\n"
        thinking_parts.append(ready)
        yield AgentEvent(type="thinking", content=ready)

        topic_start = "📝 正在生成研究主题...\n"
        thinking_parts.append(topic_start)
        yield AgentEvent(type="thinking", content=topic_start)
        topic = _CapturedStream()
        topic_messages = [
            {"role": "system", "content": self._time_context() + "\n\n" + RESEARCH_TOPIC_GENERATION},
            *state.messages,
            {"role": "user", "content": f"<original_question>{question}</original_question>"},
        ]
        async for event in self._stream_as_thinking(topic_messages, topic):
            if event.content:
                thinking_parts.append(str(event.content))
            yield event
        state.refined_research_topic = topic.text.strip() or question
        topic_done = "\n✅ 研究主题已生成\n\n"
        thinking_parts.append(topic_done)
        yield AgentEvent(type="thinking", content=topic_done)

        for _ in range(self._settings.deep_max_rounds):
            state.next_round()
            round_start = f"\n🔄 第 {state.round} 轮研究开始\n"
            thinking_parts.append(round_start)
            yield AgentEvent(type="thinking", content=round_start)

            plan_start = "📋 正在生成执行计划...\n"
            thinking_parts.append(plan_start)
            yield AgentEvent(type="thinking", content=plan_start)
            plan = await self._generate_plan(state)
            plan_done = f"\n✅ 执行计划已生成，共 {len(plan)} 个任务\n"
            thinking_parts.append(plan_done)
            yield AgentEvent(type="thinking", content=plan_done)
            if plan:
                plan_table = "\n📋 执行计划表：\n" + "".join(f"  🟠 {task.instruction} \n" for task in plan)
                thinking_parts.append(plan_table)
                yield AgentEvent(type="thinking", content=plan_table)

            if not plan or all(task.id is None for task in plan):
                break

            divider = "\n--- 开始执行任务 ---\n\n"
            thinking_parts.append(divider)
            yield AgentEvent(type="thinking", content=divider)

            results: dict[str, TaskResult] = {}
            async for event in self._execute_plan(plan, state, results, references, used_tools):
                if event.content:
                    thinking_parts.append(str(event.content))
                yield event

            execution_done = "\n--- 任务执行完成 ---\n\n"
            thinking_parts.append(execution_done)
            yield AgentEvent(type="thinking", content=execution_done)

            critique_start = "\n🔍 正在评估当前研究结果...\n"
            thinking_parts.append(critique_start)
            yield AgentEvent(type="thinking", content=critique_start)
            critique = await self._critique(state, plan, results)
            if critique.passed:
                critique_message = "\n✅ 研究结果评估通过，准备生成最终报告\n"
                thinking_parts.append(critique_message)
                yield AgentEvent(type="thinking", content=critique_message)
                break

            critique_message = f"\n⚠️ 研究结果评估未通过，原因分析：{critique.feedback}\n"
            thinking_parts.append(critique_message)
            yield AgentEvent(type="thinking", content=critique_message)
            state.add("assistant", f"【Critique Feedback】\n{critique.feedback}")

            if state.round < self._settings.deep_max_rounds:
                next_round = "\n--- 准备进入下一轮迭代 ---\n"
                thinking_parts.append(next_round)
                yield AgentEvent(type="thinking", content=next_round)
                async for event in self._compress_if_needed(state):
                    if event.content:
                        thinking_parts.append(str(event.content))
                    yield event

        research_done = "\n✅ 研究阶段完成，准备生成最终报告\n"
        thinking_parts.append(research_done)
        yield AgentEvent(type="thinking", content=research_done)
        summarize_start = "\n📝 正在生成最终研究报告...\n\n"
        thinking_parts.append(summarize_start)
        yield AgentEvent(type="thinking", content=summarize_start)

        final_answer = _CapturedStream()
        summary_messages = [
            {"role": "system", "content": self._time_context() + "\n\n" + SUMMARIZE},
            {
                "role": "user",
                "content": (
                    f"【用户原始问题】\n{state.question}\n\n"
                    f"【研究主题】\n{state.refined_research_topic or '未生成研究主题'}\n\n"
                    f"【工具检索结果】\n{state.extract_tool_results() or '（未检索到相关结果）'}"
                ),
            },
        ]
        async for event in self._stream_summary(summary_messages, final_answer):
            if event.type == "thinking" and event.content:
                thinking_parts.append(str(event.content))
            yield event

        answer = final_answer.text
        if not answer.strip():
            raise RuntimeError("Deep Research 模型未返回最终报告")
        if references:
            yield AgentEvent(type="reference", content=references, count=len(references))

        await self._finish_turn(
            turn_handle,
            question,
            answer,
            thinking_parts,
            used_tools,
            references,
            first_response_time,
            started_at,
        )
        yield AgentEvent.complete()

    async def _stream_as_thinking(
        self,
        messages: list[dict[str, Any]],
        capture: _CapturedStream,
    ) -> AsyncIterator[AgentEvent]:
        parser = ThinkTagStreamParser()
        async for delta in self._llm.stream_chat(messages, [], enable_thinking=False):
            reasoning = delta.get("reasoning_content")
            if reasoning:
                yield AgentEvent(type="thinking", content=str(reasoning))
            content = delta.get("content")
            if not content:
                continue
            for segment in parser.feed(str(content)):
                yield AgentEvent(type="thinking", content=segment.content)
                if not segment.thinking:
                    capture.text += segment.content
        for segment in parser.finish():
            yield AgentEvent(type="thinking", content=segment.content)
            if not segment.thinking:
                capture.text += segment.content

    async def _stream_summary(
        self,
        messages: list[dict[str, Any]],
        capture: _CapturedStream,
    ) -> AsyncIterator[AgentEvent]:
        parser = ThinkTagStreamParser()
        async for delta in self._llm.stream_chat(messages, [], enable_thinking=False):
            reasoning = delta.get("reasoning_content")
            if reasoning:
                yield AgentEvent(type="thinking", content=str(reasoning))
            content = delta.get("content")
            if not content:
                continue
            for segment in parser.feed(str(content)):
                if segment.thinking:
                    yield AgentEvent(type="thinking", content=segment.content)
                else:
                    capture.text += segment.content
                    yield AgentEvent(type="text", content=segment.content)
        for segment in parser.finish():
            if segment.thinking:
                yield AgentEvent(type="thinking", content=segment.content)
            else:
                capture.text += segment.content
                yield AgentEvent(type="text", content=segment.content)

    async def _generate_plan(self, state: DeepResearchState) -> list[PlanTask]:
        tool_description = self._search.definition["function"].get("description", "web search")
        response = await self._llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        self._time_context()
                        + "\n\n"
                        + PLAN
                        + f"\n\n## 当前上下文\n当前轮次: {state.round}"
                        + f"\n\n## 可用工具说明\n- {self._search.name}: {tool_description}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"【研究主题】\n{state.refined_research_topic or state.question}\n\n"
                        f"【对话历史】\n{state.render_full_context()}\n\n"
                        "如果存在【Critique Feedback】，新计划必须直接解决反馈且不要重复失败尝试。"
                    ),
                },
            ],
            [],
            enable_thinking=False,
        )
        raw = _assistant_text(response)
        value = _parse_json_value(raw)
        if not isinstance(value, list):
            raise RuntimeError("Deep Research planner 未返回 JSON 数组")
        tasks: list[PlanTask] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            task_id_raw = item.get("id")
            task_id = str(task_id_raw).strip() if task_id_raw is not None else None
            instruction = str(item.get("instruction") or "").strip()
            try:
                order = int(item.get("order", 0))
            except (TypeError, ValueError):
                order = 0
            if instruction:
                tasks.append(PlanTask(task_id or None, instruction, order))
        return tasks

    async def _execute_plan(
        self,
        plan: list[PlanTask],
        state: DeepResearchState,
        results: dict[str, TaskResult],
        references: list[dict[str, Any]],
        used_tools: set[str],
    ) -> AsyncIterator[AgentEvent]:
        grouped: dict[int, list[PlanTask]] = {}
        for task in plan:
            grouped.setdefault(task.order, []).append(task)
        accumulated: dict[str, str] = {}

        for order in sorted(grouped):
            tasks = [task for task in grouped[order] if task.id]
            if not tasks:
                continue
            dependency_context = self._build_dependency_context(accumulated, plan, order)
            for task in tasks:
                yield AgentEvent(
                    type="thinking",
                    content=f"⚙️ 正在执行任务 {task.id} : {task.instruction}\n",
                )

            pending = {
                asyncio.create_task(self._execute_task_with_retry(task, dependency_context)): task for task in tasks
            }
            try:
                for future in asyncio.as_completed(pending):
                    execution = await future
                    result = execution.result
                    results[result.task_id] = result
                    references.extend(execution.references)
                    used_tools.update(execution.used_tools)
                    if result.success and result.output is not None:
                        accumulated[result.task_id] = result.output
                        yield AgentEvent(type="thinking", content=f"执行结果: {result.output}\n\n")
                    else:
                        yield AgentEvent(
                            type="thinking",
                            content=f"\n❌ 任务 {result.task_id} 执行失败: {result.error or 'unknown error'}\n\n",
                        )
                    state.add("assistant", _task_result_message(result))
            except asyncio.CancelledError:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise

    async def _execute_task_with_retry(self, task: PlanTask, dependency_context: str) -> _TaskExecution:
        last_error: Exception | None = None
        for attempt in range(1, self._settings.deep_tool_retries + 2):
            try:
                async with self._tool_semaphore:
                    execution = await self._execute_task_once(task, dependency_context)
                execution.attempts = attempt
                return execution
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
        return _TaskExecution(
            result=TaskResult(task.id or "", False, error=str(last_error or "unknown error")),
            attempts=self._settings.deep_tool_retries + 1,
        )

    async def _execute_task_once(self, task: PlanTask, dependency_context: str) -> _TaskExecution:
        full_context = (
            f"【Available Results】\n{dependency_context}\n\n"
            f"【Current Task】\n{task.instruction}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": EXECUTE},
            {"role": "user", "content": full_context},
        ]
        references: list[dict[str, Any]] = []
        used_tools: set[str] = set()

        for round_number in range(1, self._settings.deep_task_agent_rounds + 1):
            response = await self._llm.complete(
                messages,
                [self._search.definition],
                enable_thinking=False,
            )
            message = _assistant_message(response)
            tool_calls = _normalize_tool_calls(message.get("tool_calls"), round_number)
            if not tool_calls:
                answer = str(message.get("content") or "").strip()
                if not answer:
                    raise RuntimeError("任务执行模型未返回结果")
                return _TaskExecution(
                    result=TaskResult(task.id or "", True, output=answer),
                    references=references,
                    used_tools=used_tools,
                )

            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
            tool_results = await asyncio.gather(*(self._execute_search_tool(call) for call in tool_calls))
            for tool_call, tool_result in zip(tool_calls, tool_results, strict=True):
                if tool_result[1]:
                    used_tools.add(self._search.name)
                    references.extend(tool_result[2])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": str(tool_call["function"].get("name") or "unknown"),
                        "content": tool_result[0],
                    }
                )

        response = await self._llm.complete(
            [
                *messages,
                {
                    "role": "user",
                    "content": "工具轮次已达到上限。请只基于已有工具结果输出忠实整理，不要继续调用工具。",
                },
            ],
            [],
            enable_thinking=False,
        )
        answer = _assistant_text(response).strip()
        if not answer:
            raise RuntimeError("任务执行模型达到轮次上限后仍未返回结果")
        return _TaskExecution(
            result=TaskResult(task.id or "", True, output=answer),
            references=references,
            used_tools=used_tools,
        )

    async def _execute_search_tool(self, tool_call: dict[str, Any]) -> tuple[str, bool, list[dict[str, Any]]]:
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "unknown")
        arguments = str(function.get("arguments") or "{}")
        tool_started_at = time.perf_counter()
        invoked = False
        try:
            if name != self._search.name:
                return (
                    json.dumps({"error": f"Deep Research 只允许搜索工具，收到: {name}"}, ensure_ascii=False),
                    False,
                    [],
                )
            with trace_tool_call(name):
                raw = await self._search.call(arguments)
            if isinstance(raw, dict) and raw.get("error"):
                return json.dumps(raw, ensure_ascii=False), False, []
            invoked = True
            results = raw.get("results") if isinstance(raw, dict) else None
            references = [item for item in results or [] if isinstance(item, dict) and item.get("url")]
            return json.dumps(raw, ensure_ascii=False), True, references
        finally:
            record_tool_call(
                name,
                started_at=tool_started_at,
                outcome="success" if invoked else "error",
            )

    @staticmethod
    def _build_dependency_context(results: dict[str, str], plan: list[PlanTask], current_order: int) -> str:
        if current_order == 1:
            return "无\n"
        order_by_id = {task.id: task.order for task in plan if task.id}
        rows = [
            f"{task_id}: {output}"
            for task_id, output in results.items()
            if order_by_id.get(task_id) == current_order - 1
        ]
        return ("任务 " + "\n\n".join(rows) + "\n") if rows else "无\n"

    async def _critique(
        self,
        state: DeepResearchState,
        plan: list[PlanTask],
        results: dict[str, TaskResult],
    ) -> CritiqueResult:
        plan_text = "\n".join(f"- {task.instruction}" for task in plan) or "无"
        result_rows: list[str] = []
        for task_id, result in results.items():
            if result.success and result.output is not None:
                result_rows.append(f"任务 {task_id}: {result.output}")
            elif result.error:
                result_rows.append(f"任务 {task_id}: 执行失败 - {result.error}")
        result_text = "\n\n".join(result_rows) or "无"
        response = await self._llm.complete(
            [
                {"role": "system", "content": self._time_context() + "\n\n" + CRITIQUE},
                {
                    "role": "user",
                    "content": (
                        f"【用户原始问题】\n{state.question}\n\n"
                        f"【研究主题】\n{state.refined_research_topic or '未生成研究主题'}\n\n"
                        f"【当前轮次的执行计划】\n{plan_text}\n\n"
                        f"【当前轮次的工具结果】\n{result_text}"
                    ),
                },
            ],
            [],
            enable_thinking=False,
        )
        value = _parse_json_value(_assistant_text(response))
        if not isinstance(value, dict):
            raise RuntimeError("Deep Research critique 未返回 JSON object")
        return CritiqueResult(bool(value.get("passed")), str(value.get("feedback") or ""))

    async def _compress_if_needed(self, state: DeepResearchState) -> AsyncIterator[AgentEvent]:
        if state.current_chars() < self._settings.deep_context_char_limit:
            return
        yield AgentEvent(type="thinking", content="📦 上下文过长，正在压缩...\n")
        response = await self._llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        self._time_context()
                        + "\n\n"
                        + f"最终内容总字符数不得超过 {self._settings.deep_context_char_limit}。\n"
                        + COMPRESS
                    ),
                },
                {"role": "user", "content": state.render_full_context()},
            ],
            [],
            enable_thinking=False,
        )
        snapshot = _assistant_text(response).strip()
        if not snapshot:
            raise RuntimeError("Deep Research context compression 返回空内容")
        state.messages.clear()
        state.add("system", "【Compressed Agent State】\n" + snapshot)
        yield AgentEvent(type="thinking", content="✅ 上下文压缩完成\n")

    async def _finish_turn(
        self,
        turn_handle: TurnHandle,
        question: str,
        answer: str,
        thinking_parts: list[str],
        used_tools: set[str],
        references: list[dict[str, Any]],
        first_response_time: int,
        started_at: float,
    ) -> None:
        reference_storage: str | None = None
        if references:
            reference_storage = json.dumps(
                {"type": "reference", "content": json.dumps(references, ensure_ascii=False), "count": len(references)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        await self._memory.finish_turn(
            turn_handle,
            question=question,
            answer=answer,
            thinking="".join(thinking_parts) or None,
            tools=",".join(sorted(used_tools)),
            reference=reference_storage,
            first_response_time=first_response_time,
            total_response_time=int((time.perf_counter() - started_at) * 1000),
        )

    @staticmethod
    def _time_context() -> str:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return (
            "当前正确且权威的现实系统时间："
            + now.strftime("%Y-%m-%d %H:%M:%S")
            + "。这是现实世界的当前时间，不是未来日期。"
            "任何不晚于该时间的日期都必须视为已经发生或正在发生，"
            "可通过联网搜索核验；不得因为模型训练截止时间而将其误判为未来数据。"
        )


def _task_result_message(result: TaskResult) -> str:
    rows = [
        "【Completed Task Result】",
        f"taskId: {result.task_id}",
        f"success: {str(result.success).lower()}",
    ]
    if result.output is not None:
        rows.extend(["result:", result.output])
    if result.error is not None:
        rows.extend(["error:", result.error])
    rows.append("【End Task Result】")
    return "\n".join(rows)


def _assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def _assistant_text(response: dict[str, Any]) -> str:
    return str(_assistant_message(response).get("content") or "")


def _normalize_tool_calls(raw: Any, round_number: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        result.append(
            {
                "id": str(item.get("id") or f"deep-call-{round_number}-{index}"),
                "type": "function",
                "function": {
                    "name": str(function.get("name") or "unknown"),
                    "arguments": str(function.get("arguments") or "{}"),
                },
            }
        )
    return result


def _parse_json_value(raw: str) -> Any:
    candidate = _strip_think_tags(raw).strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        starts = [position for position in (candidate.find("["), candidate.find("{")) if position >= 0]
        if not starts:
            return None
        start = min(starts)
        end = max(candidate.rfind("]"), candidate.rfind("}"))
        if end <= start:
            return None
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None


def _strip_think_tags(raw: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)


REQUIREMENT_CLARIFICATION = """你是【Deep Research 需求分析专家】，只判断需求是否足够开展研究，不直接回答。
只要能合理推断研究方向就开始研究；仅当研究对象、主题含义或范围完全无法判断时追问。
输出不超过120字。需补充时以【需要补充信息】开头并提出1-3个问题；信息足够时以【开始研究】开头。"""

RESEARCH_TOPIC_GENERATION = """你是【Deep Research 分析点规划专家】。
基于用户问题列出3-5个具体、可搜索、多维度的研究分析点；每点一行带编号，不做事实判断，不写前言总结。"""

PLAN = """你是【DeepResearch 执行计划规划专家】。只规划搜索工具任务。
每个任务必须有明确工具与检索目标；同一 order 可并行，后续依赖前序时提高 order。
不得规划纯分析、总结、判断或不调用工具的任务。若信息已充分，返回一个 id=null 的任务。
严格只输出 JSON 数组，字段为 id、instruction、order。最近一次【Critique Feedback】优先级最高。"""

EXECUTE = """你是【DeepResearch 工具执行与结果整理专家】。
只基于当前任务、依赖结果和联网搜索工具真实返回内容，关注时效性与真实性。
只提取关键事实、数据和原文结论；冲突信息如实保留；禁止引入工具未提供的信息或做价值判断。"""

CRITIQUE = """你是【DeepResearch 研究评审专家】。判断当前材料是否足以支持对外研究报告。
重点检查核心问题覆盖与证据可用性；约80%的核心需求被可靠覆盖即可通过，反复无法检索的敏感信息无需无限尝试。
严格只输出 JSON：{\"passed\": true|false, \"feedback\": \"未通过时只写最关键待补方向\"}。"""

COMPRESS = """你是【上下文内容压缩器】。这是下一轮工作记忆，不是面向人类的摘要。
必须保留用户最终目标、已完成任务结论、每次工具的关键输入/事实、最近 Critique、未解决问题；
删除重复解释和思考过程，不引入新信息。
输出结构：User Goal、Completed Work、Key Tool Results、Last Critique、Open Issues。"""

SUMMARIZE = """你是【DeepResearch 结果总结专家】。
只基于用户问题、研究主题和提供的工具检索结果生成专业、完整、结构清晰的 Markdown 深度研究报告。
不得编造未检索到的信息；冲突来源客观并列；不要提及计划、轮次或批判等中间过程；语言与用户提问一致。"""
