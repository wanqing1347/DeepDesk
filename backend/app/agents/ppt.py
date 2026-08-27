import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings
from ..files.storage import ObjectStore
from ..memory import ConversationStore, TurnHandle
from ..metrics import record_tool_call
from ..persistence.models import AiPptInst
from ..persistence.ppt_repository import PptRepository
from ..ppt.domain import PptIntent, PptStatus
from ..ppt.intent import PptIntentRecognizer
from ..ppt.providers import PptImageGenerator, PptRenderer, materialize_ppt_images, serialize_schema
from ..providers.llm import OpenAICompatibleClient
from ..schemas import AgentEvent
from ..streaming import ThinkTagStreamParser
from ..tools.web_search import WebSearchTool
from ..tracing import trace_tool_call


@dataclass(slots=True)
class _PptRunContext:
    inst: AiPptInst
    query: str
    thinking_parts: list[str]
    final_parts: list[str] = field(default_factory=list)
    modify_mode: bool = False
    stopped: bool = False


@dataclass(slots=True)
class _Capture:
    text: str = ""


@dataclass(frozen=True, slots=True)
class _ModifyTextConstraint:
    label: str
    target: str
    scope: str


class PptBuilderAgent:
    def __init__(
        self,
        settings: Settings,
        memory: ConversationStore,
        repository: PptRepository,
        renderer: PptRenderer,
        image_generator: PptImageGenerator,
        object_store: ObjectStore | None,
        *,
        llm_client: OpenAICompatibleClient | None = None,
        search_tool: WebSearchTool | None = None,
        provider_http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._repository = repository
        self._renderer = renderer
        self._image_generator = image_generator
        self._object_store = object_store
        self._llm = llm_client or OpenAICompatibleClient(settings)
        self._search = search_tool or WebSearchTool(settings)
        self._provider_http_client = provider_http_client

    async def run(self, conversation_id: str, query: str) -> AsyncIterator[AgentEvent]:
        started_at = time.perf_counter()
        turn_handle = await self._memory.begin_turn(conversation_id, query, agent_type="pptx")
        thinking_parts: list[str] = []
        first_response_time = 0

        intent = await PptIntentRecognizer(self._repository, self._llm).recognize(conversation_id, query)
        latest = await asyncio.to_thread(self._repository.get_latest_inst, conversation_id)

        if intent.intent is PptIntent.CREATE_PPT:
            message = "开始创建新的PPT...\n"
            first_response_time = self._elapsed_ms(started_at)
            thinking_parts.append(message)
            yield AgentEvent(type="thinking", content=message)
            inst = await asyncio.to_thread(self._repository.create_inst, conversation_id, query)
            context = _PptRunContext(inst=inst, query=query, thinking_parts=thinking_parts)
            async for event in self._run_state_machine(context):
                yield event
            if context.final_parts:
                await self._finish_turn(
                    turn_handle,
                    query,
                    "".join(context.final_parts),
                    thinking_parts,
                    first_response_time,
                    started_at,
                )
            yield AgentEvent.complete()
            return

        if intent.intent is PptIntent.MODIFY_PPT:
            if latest is None:
                async for event in self._terminal_message(
                    turn_handle,
                    query,
                    "当前会话中没有已生成的PPT，无法修改。请先生成一个PPT。",
                    thinking_parts,
                    started_at,
                ):
                    yield event
                return
            if not str(latest.ppt_schema or "").strip():
                async for event in self._terminal_message(
                    turn_handle,
                    query,
                    "该PPT没有Schema数据，无法修改。",
                    thinking_parts,
                    started_at,
                ):
                    yield event
                return
            message = "正在修改PPT...\n"
            first_response_time = self._elapsed_ms(started_at)
            thinking_parts.append(message)
            yield AgentEvent(type="thinking", content=message)
            for chunk in ("正在分析修改需求...\n", "正在修改PPT内容...\n"):
                thinking_parts.append(chunk)
                yield AgentEvent(type="thinking", content=chunk)
            context = _PptRunContext(
                inst=latest,
                query=query,
                thinking_parts=thinking_parts,
                modify_mode=True,
            )
            async for event in self._schema_stage(context, modify=True):
                yield event
            if not context.stopped:
                async for event in self._run_state_machine(context):
                    yield event
            if context.final_parts:
                await self._finish_turn(
                    turn_handle,
                    query,
                    "".join(context.final_parts),
                    thinking_parts,
                    first_response_time,
                    started_at,
                )
            yield AgentEvent.complete()
            return

        # RESUME_PPT
        if latest is None:
            async for event in self._terminal_message(
                turn_handle,
                query,
                "当前会话中没有PPT实例，无法继续。请先创建一个PPT。",
                thinking_parts,
                started_at,
            ):
                yield event
            return
        status = self._status(latest.status)
        if status is PptStatus.SUCCESS:
            thinking = "当前PPT已经成功生成，如果您要修改，请说明具体修改需求。\n"
            thinking_parts.append(thinking)
            first_response_time = self._elapsed_ms(started_at)
            yield AgentEvent(type="thinking", content=thinking)
            answer = "当前PPT已经成功生成。如果您需要修改，请说明具体的修改需求。"
            yield AgentEvent(type="text", content=answer)
            await self._finish_turn(
                turn_handle,
                query,
                answer,
                thinking_parts,
                first_response_time,
                started_at,
            )
            yield AgentEvent.complete()
            return

        if str(latest.error_msg or "").strip():
            latest = await asyncio.to_thread(self._repository.clear_error, latest.id, status)
        thinking = f"正在从状态 {status.value} 继续执行PPT生成...\n"
        thinking_parts.append(thinking)
        first_response_time = self._elapsed_ms(started_at)
        yield AgentEvent(type="thinking", content=thinking)
        context = _PptRunContext(inst=latest, query=query, thinking_parts=thinking_parts)
        async for event in self._run_state_machine(context):
            yield event
        if context.final_parts:
            await self._finish_turn(
                turn_handle,
                query,
                "".join(context.final_parts),
                thinking_parts,
                first_response_time,
                started_at,
            )
        yield AgentEvent.complete()

    async def _run_state_machine(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        while not context.stopped:
            fresh = await asyncio.to_thread(self._repository.get_by_id, context.inst.id)
            if fresh is None:
                raise RuntimeError(f"PPT实例不存在: {context.inst.id}")
            context.inst = fresh
            status = self._status(fresh.status)
            if status in {PptStatus.INIT, PptStatus.REQUIREMENT}:
                async for event in self._requirement_stage(context):
                    yield event
            elif status is PptStatus.SEARCH:
                async for event in self._search_stage(context):
                    yield event
            elif status is PptStatus.TEMPLATE:
                async for event in self._template_stage(context):
                    yield event
            elif status is PptStatus.OUTLINE:
                async for event in self._outline_stage(context):
                    yield event
            elif status is PptStatus.SCHEMA:
                async for event in self._schema_stage(context, modify=False):
                    yield event
            elif status is PptStatus.RENDER:
                async for event in self._render_stage(context):
                    yield event
            elif status is PptStatus.SUCCESS:
                async for event in self._success_stage(context):
                    yield event
                context.stopped = True
            elif status is PptStatus.FAILED:
                async for event in self._failure_stage(context, fresh.error_msg or "PPT生成失败"):
                    yield event
                context.stopped = True
            else:
                raise RuntimeError(f"未知PPT状态: {fresh.status}")

    async def _requirement_stage(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        start = "正在分析您的需求...\n"
        context.thinking_parts.append(start)
        yield AgentEvent(type="thinking", content=start)
        history = await self._memory.get(context.inst.conversation_id or "")
        capture = _Capture()
        messages = [
            {"role": "system", "content": REQUIREMENT_PROMPT},
            *history,
            {"role": "user", "content": f"<question>{context.query}</question>"},
        ]
        try:
            async for event in self._stream_as_thinking(messages, capture):
                if event.content:
                    context.thinking_parts.append(str(event.content))
                yield event
            response = _strip_think_tags(capture.text).strip()
            if self._should_continue_requirement(response):
                context.inst = await asyncio.to_thread(
                    self._repository.update_requirement,
                    context.inst.id,
                    response,
                    PptStatus.SEARCH,
                )
                done = "\n✅ 需求已确认，开始收集相关信息\n"
                context.thinking_parts.append(done)
                yield AgentEvent(type="thinking", content=done)
                return

            context.inst = await asyncio.to_thread(
                self._repository.update_requirement,
                context.inst.id,
                response,
                PptStatus.REQUIREMENT,
            )
            error = "需要补充信息：\n" + response
            context.inst = await asyncio.to_thread(
                self._repository.update_error,
                context.inst.id,
                error,
                PptStatus.REQUIREMENT,
            )
            async for event in self._failure_stage(context, error):
                yield event
            context.stopped = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"需求分析失败: {exc}"
            context.inst = await asyncio.to_thread(
                self._repository.update_error,
                context.inst.id,
                error,
                PptStatus.REQUIREMENT,
            )
            async for event in self._failure_stage(context, error):
                yield event
            context.stopped = True

    async def _search_stage(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        start = "正在收集相关信息...\n"
        context.thinking_parts.append(start)
        yield AgentEvent(type="thinking", content=start)
        try:
            search_result = await self._collect_search_info(str(context.inst.requirement or context.query))
            context.inst = await asyncio.to_thread(
                self._repository.update_search_info,
                context.inst.id,
                search_result,
                PptStatus.TEMPLATE,
            )
            if search_result:
                context.thinking_parts.append(search_result)
                yield AgentEvent(type="thinking", content=search_result)
            done = "\n✅相关信息收集完成，开始选择模板\n"
            context.thinking_parts.append(done)
            yield AgentEvent(type="thinking", content=done)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_stage(context, PptStatus.SEARCH, f"信息收集失败: {exc}")
            async for event in self._failure_stage(context, f"信息收集失败: {exc}"):
                yield event
            context.stopped = True

    async def _template_stage(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        start = "正在设计模板样式...\n"
        context.thinking_parts.append(start)
        yield AgentEvent(type="thinking", content=start)
        try:
            templates = await asyncio.to_thread(self._repository.get_all_templates)
            if not templates:
                raise RuntimeError("没有可用PPT模板")
            templates_info = "\n".join(
                (
                    f"template_code: {item.template_code}\n模板名称: {item.template_name}\n"
                    f"适用风格: {item.style_tags or ''}\n模板页数: {item.slide_count or 0}\n"
                    f"模板说明: {item.template_desc or ''}"
                )
                for item in templates
            )
            response = await self._llm.complete(
                [
                    {"role": "system", "content": TEMPLATE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"【需求】\n{context.inst.requirement or context.query}\n\n"
                            f"【模板】\n{templates_info}"
                        ),
                    },
                ],
                [],
            )
            payload = _parse_json_object(_assistant_text(response))
            template_code = str(payload.get("templateCode") or payload.get("template_code") or "").strip()
            if not template_code:
                raise RuntimeError("模板选择未返回 templateCode")
            context.inst = await asyncio.to_thread(
                self._repository.update_template_code,
                context.inst.id,
                template_code,
                PptStatus.OUTLINE,
            )
            done = "✅ 模板设计完成，开始生成大纲\n"
            context.thinking_parts.append(done)
            yield AgentEvent(type="thinking", content=done)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_stage(context, PptStatus.TEMPLATE, f"模板选择失败: {exc}")
            async for event in self._failure_stage(context, f"模板选择失败: {exc}"):
                yield event
            context.stopped = True

    async def _outline_stage(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        start = "正在生成PPT大纲...\n"
        context.thinking_parts.append(start)
        yield AgentEvent(type="thinking", content=start)
        try:
            template = await asyncio.to_thread(
                self._repository.get_template_by_code,
                str(context.inst.template_code or ""),
            )
            if template is None:
                error = f"模板不存在: {context.inst.template_code or ''}"
                await self._fail_stage(context, PptStatus.TEMPLATE, error)
                async for event in self._failure_stage(context, error):
                    yield event
                context.stopped = True
                return
            capture = _Capture()
            messages = [
                {
                    "role": "user",
                    "content": OUTLINE_PROMPT.format(
                        requirement=context.inst.requirement or context.query,
                        template_schema=template.template_schema,
                        template_name=template.template_name,
                        search_info=context.inst.search_info or "",
                    ),
                }
            ]
            async for event in self._stream_as_thinking(messages, capture):
                if event.content:
                    context.thinking_parts.append(str(event.content))
                yield event
            outline = _strip_think_tags(capture.text).strip()
            context.inst = await asyncio.to_thread(
                self._repository.update_outline,
                context.inst.id,
                outline,
                PptStatus.SCHEMA,
            )
            done = "\n✅ 大纲生成完成，开始设计PPT详细内容\n"
            context.thinking_parts.append(done)
            yield AgentEvent(type="thinking", content=done)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_stage(context, PptStatus.OUTLINE, f"大纲生成失败: {exc}")
            async for event in self._failure_stage(context, f"大纲生成失败: {exc}"):
                yield event
            context.stopped = True

    async def _schema_stage(self, context: _PptRunContext, *, modify: bool) -> AsyncIterator[AgentEvent]:
        start = "正在重新生成PPT详细内容...\n" if modify else "正在设计PPT详细内容...\n"
        context.thinking_parts.append(start)
        yield AgentEvent(type="thinking", content=start)
        try:
            requested_slide_count = _requested_slide_count(
                context.query,
                "" if modify else str(context.inst.requirement or ""),
            )
            modify_constraints = _extract_modify_text_constraints(context.query) if modify else []
            if modify:
                prompt = MODIFY_SCHEMA_PROMPT.format(
                    query=context.query,
                    current_schema=context.inst.ppt_schema or "{}",
                    hard_constraints=_format_schema_constraints(requested_slide_count, modify_constraints),
                )
            else:
                template = await asyncio.to_thread(
                    self._repository.get_template_by_code,
                    str(context.inst.template_code or ""),
                )
                if template is None:
                    raise RuntimeError(f"模板不存在: {context.inst.template_code or ''}")
                prompt = SCHEMA_PROMPT.format(
                    original_request=context.query,
                    template_schema=template.template_schema,
                    outline=context.inst.outline or "",
                    hard_constraints=_format_schema_constraints(requested_slide_count, []),
                )
            response = await self._llm.complete([{"role": "user", "content": prompt}], [])
            schema = _parse_json_object(_assistant_text(response))
            violations = _schema_constraint_violations(
                schema,
                requested_slide_count=requested_slide_count,
                modify_constraints=modify_constraints,
            )
            if violations:
                repair_prompt = SCHEMA_REPAIR_PROMPT.format(
                    original_prompt=prompt,
                    violations="\n".join(f"- {item}" for item in violations),
                    previous_schema=serialize_schema(schema),
                )
                repair_response = await self._llm.complete([{"role": "user", "content": repair_prompt}], [])
                schema = _parse_json_object(_assistant_text(repair_response))
                violations = _schema_constraint_violations(
                    schema,
                    requested_slide_count=requested_slide_count,
                    modify_constraints=modify_constraints,
                )
                if violations:
                    raise RuntimeError("PPT Schema未满足硬约束: " + "；".join(violations))
            _ensure_modify_constraints_renderable(schema, modify_constraints)
            slides = schema.get("slides")
            if not isinstance(slides, list):
                raise RuntimeError("PPT Schema 缺少 slides 数组")
            schema_json = serialize_schema(schema)
            context.inst = await asyncio.to_thread(
                self._repository.update_ppt_schema,
                context.inst.id,
                schema_json,
                PptStatus.RENDER,
            )

            missing_count = _missing_image_count(schema)
            if missing_count:
                for message in (
                    "✅PPT内容设计完成，开始生成图片素材\n",
                    f"共需生成 {missing_count} 张图片，开始生成...\n",
                ):
                    context.thinking_parts.append(message)
                    yield AgentEvent(type="thinking", content=message)
                outcomes = await materialize_ppt_images(
                    schema,
                    conversation_id=str(context.inst.conversation_id or ""),
                    generator=self._image_generator,
                    object_store=self._object_store,
                    download_timeout_seconds=self._settings.ppt_image_download_timeout_seconds,
                    http_client=self._provider_http_client,
                    max_retries=self._settings.provider_max_retries,
                    retry_base_seconds=self._settings.provider_retry_base_seconds,
                    retry_max_seconds=self._settings.provider_retry_max_seconds,
                )
                for index, (key, success) in enumerate(outcomes, start=1):
                    if success:
                        message = f"✅ 图片生成完成 ({index}/{missing_count})\n"
                    else:
                        message = f"⚠ 图片生成失败 ({index}/{missing_count}): \n{key}"
                    context.thinking_parts.append(message)
                    yield AgentEvent(type="thinking", content=message)
                for message in ("✅ 所有图片生成完成\n", "✅素材准备就绪，开始渲染PPT\n"):
                    context.thinking_parts.append(message)
                    yield AgentEvent(type="thinking", content=message)
                context.inst = await asyncio.to_thread(
                    self._repository.update_ppt_schema,
                    context.inst.id,
                    serialize_schema(schema),
                    PptStatus.RENDER,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_stage(context, PptStatus.SCHEMA, f"Schema生成失败: {exc}")
            async for event in self._failure_stage(context, f"Schema生成失败: {exc}"):
                yield event
            context.stopped = True

    async def _render_stage(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        start = "正在渲染PPT...\n"
        context.thinking_parts.append(start)
        yield AgentEvent(type="thinking", content=start)
        try:
            template = await asyncio.to_thread(
                self._repository.get_template_by_code,
                str(context.inst.template_code or ""),
            )
            if template is None:
                raise RuntimeError(f"模板不存在: {context.inst.template_code or ''}")
            file_url = await self._renderer.render(context.inst, template, str(context.inst.ppt_schema or "{}"))
            context.inst = await asyncio.to_thread(
                self._repository.update_file_url,
                context.inst.id,
                file_url,
                PptStatus.SUCCESS,
            )
            done = "✅ PPT渲染完成\n"
            context.thinking_parts.append(done)
            yield AgentEvent(type="thinking", content=done)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_stage(context, PptStatus.RENDER, f"PPT渲染失败: {exc}")
            async for event in self._failure_stage(context, f"PPT渲染失败: {exc}"):
                yield event
            context.stopped = True

    async def _success_stage(self, context: _PptRunContext) -> AsyncIterator[AgentEvent]:
        page_count = _page_count(context.inst.ppt_schema)
        if context.modify_mode:
            prompt = MODIFY_SUMMARY_PROMPT.format(query=context.query, file_url=context.inst.file_url or "")
        else:
            prompt = SUMMARY_PROMPT.format(
                requirement=context.inst.requirement or context.query,
                file_url=context.inst.file_url or "",
                page_count=page_count,
            )
        capture = _Capture()
        async for event in self._stream_as_answer([{"role": "user", "content": prompt}], capture):
            if event.type == "thinking" and event.content:
                context.thinking_parts.append(str(event.content))
            elif event.type == "text" and event.content:
                context.final_parts.append(str(event.content))
            yield event
        if not capture.text.strip():
            fallback = f"PPT已生成：{context.inst.file_url or ''}"
            context.final_parts.append(fallback)
            yield AgentEvent(type="text", content=fallback)

    async def _failure_stage(self, context: _PptRunContext, error_msg: str) -> AsyncIterator[AgentEvent]:
        prompt = FAILURE_PROMPT.format(error=error_msg, thinking="".join(context.thinking_parts))
        capture = _Capture()
        try:
            async for event in self._stream_as_answer([{"role": "user", "content": prompt}], capture):
                if event.type == "thinking" and event.content:
                    context.thinking_parts.append(str(event.content))
                elif event.type == "text" and event.content:
                    context.final_parts.append(str(event.content))
                yield event
        except asyncio.CancelledError:
            raise
        except Exception:
            fallback = error_msg or "PPT生成失败，请重试"
            context.final_parts.append(fallback)
            yield AgentEvent(type="text", content=fallback)

    async def _collect_search_info(self, requirement: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SEARCH_PROMPT},
            {"role": "user", "content": requirement},
        ]
        for round_number in range(1, self._settings.max_agent_rounds + 1):
            response = await self._llm.complete(messages, [self._search.definition])
            message = _assistant_message(response)
            tool_calls = _normalize_tool_calls(message.get("tool_calls"), round_number)
            if not tool_calls:
                return _clean_search_result(_strip_think_tags(str(message.get("content") or "")))
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
            results = await asyncio.gather(*(self._execute_search_tool(call) for call in tool_calls))
            for call, result in zip(tool_calls, results, strict=True):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": str(call["function"].get("name") or "unknown"),
                        "content": result,
                    }
                )
        response = await self._llm.complete(
            [*messages, {"role": "user", "content": "请基于已有搜索结果直接整理信息，不再调用工具。"}],
            [],
        )
        return _clean_search_result(_strip_think_tags(_assistant_text(response)))

    async def _execute_search_tool(self, call: dict[str, Any]) -> str:
        function = call.get("function") or {}
        tool_name = str(function.get("name") or "unknown")
        tool_started_at = time.perf_counter()
        invoked = False
        try:
            if tool_name != self._search.name:
                return json.dumps({"error": "PPT信息收集只允许搜索工具"}, ensure_ascii=False)
            arguments = str(function.get("arguments") or "{}")
            with trace_tool_call(tool_name):
                result = await self._search.call(arguments)
            invoked = True
            return json.dumps(result, ensure_ascii=False)
        finally:
            record_tool_call(
                tool_name,
                started_at=tool_started_at,
                outcome="success" if invoked else "error",
            )

    async def _stream_as_thinking(
        self,
        messages: list[dict[str, Any]],
        capture: _Capture,
    ) -> AsyncIterator[AgentEvent]:
        parser = ThinkTagStreamParser()
        async for delta in self._llm.stream_chat(messages, []):
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

    async def _stream_as_answer(
        self,
        messages: list[dict[str, Any]],
        capture: _Capture,
    ) -> AsyncIterator[AgentEvent]:
        parser = ThinkTagStreamParser()
        async for delta in self._llm.stream_chat(messages, []):
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

    async def _terminal_message(
        self,
        turn_handle: TurnHandle,
        question: str,
        answer: str,
        thinking_parts: list[str],
        started_at: float,
    ) -> AsyncIterator[AgentEvent]:
        first_response_time = self._elapsed_ms(started_at)
        yield AgentEvent(type="text", content=answer)
        await self._finish_turn(
            turn_handle,
            question,
            answer,
            thinking_parts,
            first_response_time,
            started_at,
        )
        yield AgentEvent.complete()

    async def _finish_turn(
        self,
        turn_handle: TurnHandle,
        question: str,
        answer: str,
        thinking_parts: list[str],
        first_response_time: int,
        started_at: float,
    ) -> None:
        await self._memory.finish_turn(
            turn_handle,
            question=question,
            answer=answer,
            thinking="".join(thinking_parts) or None,
            first_response_time=first_response_time,
            total_response_time=self._elapsed_ms(started_at),
        )

    async def _fail_stage(self, context: _PptRunContext, status: PptStatus, error: str) -> None:
        context.inst = await asyncio.to_thread(
            self._repository.update_error,
            context.inst.id,
            error,
            status,
        )

    @staticmethod
    def _status(raw: str | None) -> PptStatus:
        try:
            return PptStatus(str(raw or PptStatus.INIT.value))
        except ValueError:
            return PptStatus.FAILED

    @staticmethod
    def _should_continue_requirement(response: str) -> bool:
        if not response.strip():
            return False
        normalized = response.strip().lower()
        if "【开始生成ppt】" in normalized:
            return True
        if "【暂停生成ppt】" in normalized:
            return False
        stop_keywords = (
            "请问",
            "请问您",
            "请问是否",
            "请提供",
            "请问需要",
            "请问想",
            "请问希望",
            "请问要",
            "请问您的",
        )
        return not any(keyword in normalized for keyword in stop_keywords)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)


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
        if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
            continue
        function = item["function"]
        result.append(
            {
                "id": str(item.get("id") or f"ppt-call-{round_number}-{index}"),
                "type": "function",
                "function": {
                    "name": str(function.get("name") or "unknown"),
                    "arguments": str(function.get("arguments") or "{}"),
                },
            }
        )
    return result


def _parse_json_object(raw: str) -> dict[str, Any]:
    candidate = _strip_think_tags(raw).strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON结果不是object")
    return value


def _strip_think_tags(raw: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.IGNORECASE | re.DOTALL)


def _clean_search_result(raw: str) -> str:
    cleaned = re.sub(r"<tool_calls>.*?</tool_calls>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"\[Tool Call.*?\]", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"Tool call:.*?\n", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[TOOL_CALL\].*?\[/TOOL_CALL\]", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _missing_image_count(schema: dict[str, Any]) -> int:
    total = 0
    slides = schema.get("slides")
    if not isinstance(slides, list):
        return 0
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get("data"), dict):
            continue
        for raw_field in slide["data"].values():
            if not isinstance(raw_field, dict):
                continue
            if str(raw_field.get("type") or "").lower() not in {"image", "background"}:
                continue
            if str(raw_field.get("url") or "").strip():
                continue
            if str(raw_field.get("content") or "").strip():
                total += 1
    return total


def _page_count(raw_schema: str | None) -> int:
    try:
        payload = json.loads(raw_schema or "{}")
    except json.JSONDecodeError:
        return 0
    slides = payload.get("slides") if isinstance(payload, dict) else None
    return len(slides) if isinstance(slides, list) else 0


def _requested_slide_count(*texts: str) -> int | None:
    patterns = (
        re.compile(r"(?<!\d)(\d{1,2})\s*(?:页|頁)"),
        re.compile(r"(?<![A-Za-z0-9])(\d{1,2})\s*(?:slides?|pages?)(?![A-Za-z])", re.IGNORECASE),
        re.compile(r"([一二三四五六七八九十]{1,3})\s*(?:页|頁)"),
    )
    for text in texts:
        if not text:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match is None:
                continue
            raw = match.group(1)
            value = int(raw) if raw.isdigit() else _small_chinese_number(raw)
            if value is not None and 1 <= value <= 50:
                return value
    return None


def _small_chinese_number(raw: str) -> int | None:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if raw in digits:
        return digits[raw]
    if raw == "十":
        return 10
    if "十" not in raw:
        return None
    left, right = raw.split("十", 1)
    tens = digits.get(left, 1) if left else 1
    ones = digits.get(right, 0) if right else 0
    value = tens * 10 + ones
    return value if 1 <= value <= 99 else None


def _extract_modify_text_constraints(query: str) -> list[_ModifyTextConstraint]:
    pattern = re.compile(
        r"(?:把|将)?\s*(?P<field>[^，,。！？!?；;\n]{0,30}?)(?:改成|改为|修改成|修改为|替换成|替换为)"
        r"\s*[\"'“”‘’「」『』]*(?P<target>[^，,。！？!?；;\n]+)"
    )
    constraints: list[_ModifyTextConstraint] = []
    seen: set[tuple[str, str]] = set()
    for match in pattern.finditer(query):
        field = match.group("field").strip()
        target = match.group("target").strip().strip("\"'“”‘’「」『』").strip()
        if not target:
            continue
        if "封面" in field and "标题" in field:
            scope = "cover_title"
            label = "封面标题"
        elif "标题" in field:
            scope = "title"
            label = field or "标题"
        else:
            scope = "text"
            label = field or "指定文本"
        key = (scope, target)
        if key in seen:
            continue
        seen.add(key)
        constraints.append(_ModifyTextConstraint(label=label, target=target, scope=scope))
    return constraints


def _format_schema_constraints(
    requested_slide_count: int | None,
    modify_constraints: list[_ModifyTextConstraint],
) -> str:
    constraints: list[str] = []
    if requested_slide_count is not None:
        constraints.append(f"slides 数组必须恰好包含 {requested_slide_count} 页，不得增加或减少。")
    for item in modify_constraints:
        constraints.append(f"{item.label}的 content 必须精确等于「{item.target}」，不得同义改写、扩写或缩写。")
    return "\n".join(f"- {item}" for item in constraints) if constraints else "- 无额外硬约束。"


def _schema_constraint_violations(
    schema: dict[str, Any],
    *,
    requested_slide_count: int | None,
    modify_constraints: list[_ModifyTextConstraint],
) -> list[str]:
    slides = schema.get("slides")
    if not isinstance(slides, list):
        return ["PPT Schema 缺少 slides 数组"]

    violations: list[str] = []
    if requested_slide_count is not None and len(slides) != requested_slide_count:
        violations.append(f"要求 {requested_slide_count} 页，实际 {len(slides)} 页")
    for constraint in modify_constraints:
        if not _modify_constraint_satisfied(slides, constraint):
            violations.append(f"{constraint.label}未精确修改为「{constraint.target}」")
    return violations


def _modify_constraint_satisfied(slides: list[Any], constraint: _ModifyTextConstraint) -> bool:
    return any(
        str(field.get("content") or "").strip() == constraint.target
        for field in _modify_constraint_fields(slides, constraint)
    )


def _modify_constraint_fields(slides: list[Any], constraint: _ModifyTextConstraint) -> list[dict[str, Any]]:
    if constraint.scope == "cover_title":
        candidates = [
            slide
            for slide in slides
            if isinstance(slide, dict) and str(slide.get("pageType") or "").upper() == "COVER"
        ]
        slide = candidates[0] if candidates else (slides[0] if slides and isinstance(slides[0], dict) else None)
        if not isinstance(slide, dict):
            return []
        data = slide.get("data")
        title = data.get("title") if isinstance(data, dict) else None
        return [title] if isinstance(title, dict) else []

    fields: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        data = slide.get("data")
        if not isinstance(data, dict):
            continue
        for key, raw_field in data.items():
            if not isinstance(raw_field, dict):
                continue
            if constraint.scope == "title" and "title" not in str(key).lower():
                continue
            if constraint.scope == "text" and str(raw_field.get("type") or "").lower() != "text":
                continue
            fields.append(raw_field)
    return fields


def _ensure_modify_constraints_renderable(
    schema: dict[str, Any],
    constraints: list[_ModifyTextConstraint],
) -> None:
    slides = schema.get("slides")
    if not isinstance(slides, list):
        return
    for constraint in constraints:
        for schema_field in _modify_constraint_fields(slides, constraint):
            if str(schema_field.get("content") or "").strip() != constraint.target:
                continue
            for limit_key in ("fontLimit", "font-limit"):
                if limit_key not in schema_field:
                    continue
                try:
                    current_limit = int(schema_field.get(limit_key) or 0)
                except (TypeError, ValueError):
                    current_limit = 0
                if current_limit < len(constraint.target):
                    schema_field[limit_key] = len(constraint.target)


REQUIREMENT_PROMPT = """你是PPT需求分析助手。判断信息是否足够生成PPT。
信息足够时输出【开始生成PPT】并总结主题、受众、风格和核心内容；信息不足时输出【暂停生成PPT】并提出必要问题。"""

SEARCH_PROMPT = """你是PPT资料收集助手。需要事实或背景时调用 web_search，最终只整理与PPT需求直接相关的可靠信息。"""

TEMPLATE_PROMPT = """你是PPT模板选择器。根据需求从提供模板中选择一个最匹配模板。
只输出JSON：{"templateCode":"模板编码","reason":"原因"}。"""

OUTLINE_PROMPT = """根据以下需求、模板结构和搜索资料生成PPT大纲。只输出大纲内容。
【需求】
{requirement}
【模板名称】
{template_name}
【模板Schema】
{template_schema}
【搜索资料】
{search_info}
"""

SCHEMA_PROMPT = """根据模板Schema、PPT大纲和原始用户需求生成最终PPT JSON Schema。
严格保持模板字段名和字段类型；slides 每项包含 pageType/pageDesc/templatePageIndex/data。
text字段包含content/fontLimit；image/background字段可用content描述待生成图片，url可为空。
硬约束优先级高于大纲；如果大纲页数与硬约束冲突，必须重组大纲内容以满足硬约束。
只输出JSON object。
【原始用户需求】
{original_request}
【硬约束】
{hard_constraints}
【模板Schema】
{template_schema}
【大纲】
{outline}
"""

MODIFY_SCHEMA_PROMPT = """根据用户修改需求修改现有PPT Schema，未要求修改的页面和字段保持不变。
明确指定的文本替换必须逐字生效，不能只改变其他字段或在别处附加目标文本。
只输出完整JSON object。
【修改需求】
{query}
【硬约束】
{hard_constraints}
【当前Schema】
{current_schema}
"""

SCHEMA_REPAIR_PROMPT = """上一次生成的PPT Schema未满足硬约束。请修复后输出完整JSON object。
不得解释，不得输出Markdown fence，不得忽略任何未满足项。
【原始任务】
{original_prompt}
【未满足的硬约束】
{violations}
【上一次Schema】
{previous_schema}
"""

SUMMARY_PROMPT = """PPT已经生成完成。请用自然语言告诉用户生成结果，说明页数并提供文件链接。
需求：{requirement}
页数：{page_count}
文件：{file_url}
"""

MODIFY_SUMMARY_PROMPT = """PPT修改已经完成。请简洁说明修改完成并提供最新文件链接。
修改需求：{query}
文件：{file_url}
"""

FAILURE_PROMPT = """PPT生成未完成。请用自然语言向用户说明当前遇到的问题，并提示可以补充信息或重试。
错误：{error}
过程：{thinking}
"""
