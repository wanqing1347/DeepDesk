import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class CompletionClient(Protocol):
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(slots=True, frozen=True)
class ContextPolicy:
    token_threshold: int = 60_000
    keep_recent_tools: int = 4
    max_tool_length: int = 200
    protected_tools: frozenset[str] = field(default_factory=lambda: frozenset({"Skill", "read_skill"}))


class ContextCompactor:
    def __init__(self, policy: ContextPolicy, llm: CompletionClient) -> None:
        self._policy = policy
        self._llm = llm

    async def compact(self, messages: list[dict[str, Any]], current_question: str | None = None) -> None:
        if len(messages) <= 2:
            return
        self._micro_compact(messages)
        if estimate_tokens(messages) > self._policy.token_threshold:
            await self._auto_compact(messages, current_question)

    def _micro_compact(self, messages: list[dict[str, Any]]) -> None:
        tool_messages = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
        assistant_tool_messages = [
            index
            for index, message in enumerate(messages)
            if message.get("role") == "assistant" and message.get("tool_calls")
        ]

        clear_tool_count = max(0, len(tool_messages) - self._policy.keep_recent_tools)
        for index in tool_messages[:clear_tool_count]:
            message = messages[index]
            tool_name = str(message.get("name") or "unknown")
            content = str(message.get("content") or "")
            if self._is_protected(tool_name) or len(content) <= self._policy.max_tool_length:
                continue
            compacted = {
                "compacted": True,
                "tool": tool_name,
                "originalLength": len(content),
                "message": "content compressed",
            }
            message["content"] = json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))

        clear_assistant_count = max(0, len(assistant_tool_messages) - self._policy.keep_recent_tools)
        for index in assistant_tool_messages[:clear_assistant_count]:
            tool_calls = messages[index].get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = str(function.get("name") or "unknown")
                arguments = str(function.get("arguments") or "")
                if self._is_protected(name) or len(arguments) <= self._policy.max_tool_length:
                    continue
                function["arguments"] = json.dumps(
                    {
                        "compacted": True,
                        "tool": name,
                        "originalLength": len(arguments),
                        "message": "args compressed",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )

    async def _auto_compact(self, messages: list[dict[str, Any]], current_question: str | None) -> None:
        system_message = messages[0] if messages and messages[0].get("role") == "system" else None
        start = 1 if system_message is not None else 0
        old_messages = messages[start:]
        conversation_text = _conversation_text(old_messages)
        try:
            response = await self._llm.complete(
                [
                    {"role": "system", "content": _summary_system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            "请将以下对话记录压缩为结构化摘要。\n\n"
                            f"## 当前用户请求\n{current_question or '无'}\n\n"
                            f"## 对话记录\n{conversation_text}"
                        ),
                    },
                ],
                [],
            )
            summary = _assistant_text(response).strip()
            if not summary:
                raise RuntimeError("摘要模型返回空内容")
        except Exception:
            summary = _truncation_fallback(old_messages)

        messages.clear()
        if system_message is not None:
            messages.append(system_message)
        messages.append({"role": "user", "content": "[对话已压缩] 以下是之前对话的摘要：\n" + summary})

    def _is_protected(self, tool_name: str) -> bool:
        return tool_name in self._policy.protected_tools


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    cjk = 0
    other = 0
    for message in messages:
        text = _message_text(message)
        for char in text:
            if _is_cjk(char):
                cjk += 1
            else:
                other += 1
    return int(cjk / 1.5 + other / 4.0)


def _message_text(message: dict[str, Any]) -> str:
    parts = [str(message.get("content") or "")]
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if isinstance(function, dict):
                parts.append(str(function.get("name") or ""))
                parts.append(str(function.get("arguments") or ""))
    return "\n".join(parts)


def _conversation_text(messages: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for message in messages:
        rows.append(f"[{str(message.get('role') or 'unknown').upper()}] {_message_text(message)}")
    return "\n\n".join(rows)


def _truncation_fallback(messages: list[dict[str, Any]]) -> str:
    recent = messages[-10:]
    return "...[摘要生成失败，以下为最近 10 条对话内容]\n\n" + _conversation_text(recent)


def _assistant_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def _summary_system_prompt() -> str:
    return """你是对话摘要助手。请生成能让 Agent 无缝继续任务的结构化摘要。
必须保留：用户完整意图、精确文件路径/URL/变量名、已加载 Skill 的核心规则、
已完成工具调用及关键结果、当前进度和下一步具体操作。禁止输出思考过程。"""


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x2E80 <= code <= 0x2EFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
    )
