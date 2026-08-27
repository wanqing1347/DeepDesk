import asyncio
import json
import os
import shlex
from pathlib import Path
from typing import Any, ClassVar

from .local_workspace import SafeWorkspace


class RestrictedBashTool:
    """A deliberately restricted command runner for Skills Agent.

    Shell access is intentionally restricted. This implementation keeps the
    tool name/shape but defaults to disabled and only permits a small command
    subset when explicitly enabled. No shell is spawned, so pipes/redirection,
    command substitution and shell chaining are unavailable by design.
    """

    name = "bash"
    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "在受限 Skills workspace 中执行允许的命令。默认关闭；不支持管道、重定向、shell chaining。"
                "文件读取/编辑应优先使用专用工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "restart": {"type": "boolean", "default": False},
                    "timeoutMs": {"type": "integer", "minimum": 1},
                },
                "required": ["command"],
            },
        },
    }

    _FORBIDDEN_META: ClassVar[tuple[str, ...]] = ("|", ">", "<", "&&", "||", ";", "`", "$(", "\n", "\r")
    _SAFE_GIT_SUBCOMMANDS: ClassVar[frozenset[str]] = frozenset(
        {"status", "diff", "log", "show", "rev-parse", "grep", "ls-files"}
    )

    def __init__(
        self,
        workspace: SafeWorkspace,
        *,
        enabled: bool,
        allowed_commands: list[str],
        timeout_seconds: int = 30,
        max_output_bytes: int = 100_000,
    ) -> None:
        self._workspace = workspace
        self._enabled = enabled
        self._allowed_commands = {command.lower() for command in allowed_commands}
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes

    async def call(self, arguments: str) -> str:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "Error: 工具参数必须是 JSON object"
        if not isinstance(payload, dict):
            return "Error: 工具参数必须是 JSON object"
        command = str(payload.get("command") or "").strip()
        if not command:
            return "Error: command 不能为空"
        if not self._enabled:
            return "Error: bash 工具默认关闭；需显式设置 SKILLS_BASH_ENABLED=true"
        timeout_ms = payload.get("timeoutMs")
        timeout = min(
            max(float(timeout_ms) / 1000.0, 0.001) if timeout_ms is not None else self._timeout_seconds,
            float(self._timeout_seconds),
        )
        try:
            return await self._run(command, timeout)
        except Exception as exc:
            return f"Error executing command: {exc}"

    async def _run(self, command: str, timeout: float) -> str:
        if any(token in command for token in self._FORBIDDEN_META):
            raise ValueError("不允许 shell chaining、管道、重定向或命令替换")
        try:
            args = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            raise ValueError(f"命令解析失败: {exc}") from exc
        if not args:
            raise ValueError("command 不能为空")

        executable = Path(args[0]).name.lower()
        if executable in {"pwd", "cd"}:
            if len(args) != 1:
                raise ValueError(f"{executable} 不接受参数；工作目录固定在 Skills workspace")
            return str(self._workspace.root)
        if executable in {"ls", "dir"}:
            if len(args) > 2:
                raise ValueError("受限 ls/dir 最多接受一个 workspace 内路径")
            target = self._workspace.resolve(args[1] if len(args) == 2 else ".", must_exist=True)
            if not target.is_dir():
                raise NotADirectoryError(target)
            return "\n".join(sorted(item.name + ("/" if item.is_dir() else "") for item in target.iterdir()))

        if executable not in self._allowed_commands:
            raise PermissionError(f"命令不在允许列表: {executable}")
        if executable == "git" and (len(args) < 2 or args[1].lower() not in self._SAFE_GIT_SUBCOMMANDS):
            raise PermissionError("git 仅允许只读子命令: status/diff/log/show/rev-parse/grep/ls-files")

        self._workspace.ensure_root()
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self._workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return await self._finish_process(process, timeout)

    async def _finish_process(self, process: asyncio.subprocess.Process, timeout: float) -> str:
        try:
            async with asyncio.timeout(timeout):
                output, truncated = await self._read_bounded_output(process)
        except TimeoutError as exc:
            await self._terminate(process)
            raise TimeoutError(f"命令执行超时（>{timeout:g}s）") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise

        text = output.decode("utf-8", errors="replace").strip()
        if truncated:
            text = (text + "\n...[output truncated; process terminated]").strip()
        if process.returncode != 0:
            text = (text + f"\n[Exit code: {process.returncode}]").strip()
        return text

    async def _read_bounded_output(self, process: asyncio.subprocess.Process) -> tuple[bytes, bool]:
        if process.stdout is None:
            await process.wait()
            return b"", False

        output = bytearray()
        truncated = False
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                break
            remaining = self._max_output_bytes - len(output)
            if remaining <= 0:
                truncated = True
                break
            output.extend(chunk[:remaining])
            if len(chunk) > remaining or len(output) >= self._max_output_bytes:
                truncated = True
                break

        if truncated:
            await self._terminate(process)
        else:
            await process.wait()
        return bytes(output), truncated

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            process.kill()
        await process.wait()
