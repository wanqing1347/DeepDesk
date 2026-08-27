import asyncio
import fnmatch
import json
import re
from pathlib import Path
from typing import Any, ClassVar

from .filesystem import FileSystemToolset
from .local_workspace import SafeWorkspace, WorkspaceBoundaryError


class GrepTool:
    name = "grep"
    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {
            "name": name,
            "description": "在 Skills workspace 内按正则表达式搜索文件内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "glob": {"type": "string"},
                    "outputMode": {
                        "type": "string",
                        "enum": ["content", "files_with_matches", "count"],
                        "default": "content",
                    },
                    "beforeContext": {"type": "integer", "minimum": 0, "default": 0},
                    "afterContext": {"type": "integer", "minimum": 0, "default": 0},
                    "ignoreCase": {"type": "boolean", "default": False},
                    "headLimit": {"type": "integer", "minimum": 1, "default": 250},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "required": ["pattern"],
            },
        },
    }

    def __init__(
        self,
        workspace: SafeWorkspace,
        *,
        head_limit: int = 250,
        max_file_size_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self._workspace = workspace
        self._head_limit = head_limit
        self._max_file_size_bytes = max_file_size_bytes

    async def call(self, arguments: str) -> str:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "Error: 工具参数必须是 JSON object"
        if not isinstance(payload, dict):
            return "Error: 工具参数必须是 JSON object"
        try:
            return await asyncio.to_thread(self._search, payload)
        except (WorkspaceBoundaryError, FileNotFoundError, ValueError, re.error) as exc:
            return f"Error: {exc}"
        except OSError as exc:
            return f"Error: {exc}"

    def _search(self, payload: dict[str, Any]) -> str:
        pattern = str(payload.get("pattern") or "")
        if not pattern:
            raise ValueError("pattern 不能为空")
        target = self._workspace.resolve(str(payload.get("path") or "."), must_exist=True)
        glob_pattern = str(payload.get("glob") or "").strip() or None
        output_mode = str(payload.get("outputMode") or "content")
        if output_mode not in {"content", "files_with_matches", "count"}:
            raise ValueError(f"不支持的 outputMode: {output_mode}")
        before = max(0, int(payload.get("beforeContext", 0)))
        after = max(0, int(payload.get("afterContext", 0)))
        flags = re.IGNORECASE if bool(payload.get("ignoreCase", False)) else 0
        regex = re.compile(pattern, flags)
        head_limit = max(1, int(payload.get("headLimit", self._head_limit)))
        offset = max(0, int(payload.get("offset", 0)))

        files = self._candidate_files(target, glob_pattern)
        results: list[str] = []
        for file_path in files:
            matches = self._search_file(file_path, regex, output_mode, before, after)
            results.extend(matches)
        page = results[offset : offset + head_limit]
        return "\n".join(page) if page else "No matches found"

    def _candidate_files(self, target: Path, glob_pattern: str | None) -> list[Path]:
        candidates = [target] if target.is_file() else [path for path in target.rglob("*") if path.is_file()]

        safe: list[Path] = []
        for candidate in candidates:
            if glob_pattern and not fnmatch.fnmatch(candidate.name, glob_pattern):
                continue
            try:
                resolved = self._workspace.resolve(str(candidate), must_exist=True)
            except WorkspaceBoundaryError:
                continue
            if resolved.stat().st_size <= self._max_file_size_bytes:
                safe.append(resolved)
        return sorted(safe, key=lambda item: item.as_posix().lower())

    def _search_file(
        self,
        file_path: Path,
        regex: re.Pattern[str],
        output_mode: str,
        before: int,
        after: int,
    ) -> list[str]:
        try:
            content = FileSystemToolset._read_text(file_path)
        except OSError:
            return []
        lines = content.splitlines()
        matched_indices = [index for index, line in enumerate(lines) if regex.search(line)]
        if not matched_indices:
            return []

        display = self._workspace.display(file_path)
        if output_mode == "files_with_matches":
            return [display]
        if output_mode == "count":
            return [f"{display}:{len(matched_indices)}"]

        included: set[int] = set()
        for index in matched_indices:
            included.update(range(max(0, index - before), min(len(lines), index + after + 1)))
        results: list[str] = []
        for index in sorted(included):
            marker = ":" if index in matched_indices else "-"
            results.append(f"{display}{marker}{index + 1}{marker}{lines[index]}")
        return results
