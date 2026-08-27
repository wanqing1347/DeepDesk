import asyncio
import json
from pathlib import Path
from typing import Any, ClassVar

from .local_workspace import SafeWorkspace, WorkspaceBoundaryError


class FileSystemToolset:
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    GLOB_FILES = "glob_files"
    LIST_FILES = "list_files"

    definitions: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "function",
            "function": {
                "name": READ_FILE,
                "description": "读取 Skills workspace 内的文本文件，支持 offset/limit 分页并返回行号。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1},
                    },
                    "required": ["filePath"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": WRITE_FILE,
                "description": "在 Skills workspace 内创建新文件。已有文件不会被覆盖，应使用 edit_file。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["filePath", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": EDIT_FILE,
                "description": "在 Skills workspace 内通过精确字符串替换编辑已有文本文件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "oldString": {"type": "string"},
                        "newString": {"type": "string"},
                        "replaceAll": {"type": "boolean", "default": False},
                    },
                    "required": ["filePath", "oldString", "newString"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": GLOB_FILES,
                "description": "在 Skills workspace 内按 glob pattern 查找文件，例如 **/*.py。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": LIST_FILES,
                "description": "列出 Skills workspace 内目录内容，可选择递归。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "recursive": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                    },
                },
            },
        },
    ]

    def __init__(
        self,
        workspace: SafeWorkspace,
        *,
        max_file_size_bytes: int = 10 * 1024 * 1024,
        default_line_limit: int = 500,
    ) -> None:
        self._workspace = workspace
        self._max_file_size_bytes = max_file_size_bytes
        self._default_line_limit = default_line_limit

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self.definitions}

    async def call(self, name: str, arguments: str) -> str:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "Error: 工具参数必须是 JSON object"
        if not isinstance(payload, dict):
            return "Error: 工具参数必须是 JSON object"

        handler = {
            self.READ_FILE: self._read_file,
            self.WRITE_FILE: self._write_file,
            self.EDIT_FILE: self._edit_file,
            self.GLOB_FILES: self._glob_files,
            self.LIST_FILES: self._list_files,
        }.get(name)
        if handler is None:
            return f"Error: 工具未找到: {name}"
        try:
            return await asyncio.to_thread(handler, payload)
        except (WorkspaceBoundaryError, FileNotFoundError, IsADirectoryError, NotADirectoryError, ValueError) as exc:
            return f"Error: {exc}"
        except OSError as exc:
            return f"Error: {exc}"

    def _read_file(self, payload: dict[str, Any]) -> str:
        file_path = str(payload.get("filePath") or "").strip()
        if not file_path:
            raise ValueError("filePath 不能为空")
        path = self._workspace.resolve(file_path, must_exist=True)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        self._check_size(path)

        content = self._read_text(path)
        if not content.strip():
            return "System reminder: File exists but has empty contents"

        offset = int(payload.get("offset", 0))
        limit = int(payload.get("limit", self._default_line_limit))
        if offset < 0:
            raise ValueError("Line offset cannot be negative")
        if limit <= 0:
            raise ValueError("limit 必须大于 0")

        lines = content.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if offset >= len(lines):
            raise ValueError(f"Line offset {offset} exceeds file length ({len(lines)} lines)")
        selected = lines[offset : offset + limit]
        return self._format_lines(selected, offset + 1)

    def _write_file(self, payload: dict[str, Any]) -> str:
        file_path = str(payload.get("filePath") or "").strip()
        if not file_path:
            raise ValueError("filePath 不能为空")
        content = str(payload.get("content") or "")
        path = self._workspace.resolve(file_path)
        if path.exists():
            raise ValueError(f"File already exists: {self._workspace.display(path)}; 请使用 edit_file")
        self._workspace.ensure_root()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Resolve again after parent creation so an existing symlink parent can
        # never redirect a write outside the configured workspace.
        path = self._workspace.resolve(file_path)
        path.write_text(content, encoding="utf-8")
        return f"Successfully created file: {self._workspace.display(path)}"

    def _edit_file(self, payload: dict[str, Any]) -> str:
        file_path = str(payload.get("filePath") or "").strip()
        if not file_path:
            raise ValueError("filePath 不能为空")
        path = self._workspace.resolve(file_path, must_exist=True)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        self._check_size(path)

        old = str(payload.get("oldString") or "")
        new = str(payload.get("newString") or "")
        replace_all = bool(payload.get("replaceAll", False))
        if not old:
            raise ValueError("oldString 不能为空")
        if old == new:
            raise ValueError("newString 必须与 oldString 不同")

        content = self._read_text(path)
        matches = content.count(old)
        if matches == 0:
            raise ValueError("oldString 未在文件中找到")
        if matches > 1 and not replace_all:
            raise ValueError(f"oldString 在文件中出现 {matches} 次，请提供更多上下文或设置 replaceAll=true")
        updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        return f"Successfully edited file: {self._workspace.display(path)}"

    def _glob_files(self, payload: dict[str, Any]) -> str:
        pattern = str(payload.get("pattern") or "").strip()
        if not pattern:
            raise ValueError("pattern 不能为空")
        base = self._workspace.resolve(str(payload.get("path") or "."), must_exist=True)
        if not base.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._workspace.display(base)}")
        limit = max(1, min(int(payload.get("limit", 200)), 1000))

        matches: list[str] = []
        for candidate in sorted(base.glob(pattern), key=lambda item: item.as_posix().lower()):
            try:
                resolved = self._workspace.resolve(str(candidate), must_exist=True)
            except WorkspaceBoundaryError:
                continue
            if resolved.is_file():
                matches.append(self._workspace.display(resolved))
            if len(matches) >= limit:
                break
        return "\n".join(matches) if matches else "No files matched"

    def _list_files(self, payload: dict[str, Any]) -> str:
        base = self._workspace.resolve(str(payload.get("path") or "."), must_exist=True)
        if not base.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._workspace.display(base)}")
        recursive = bool(payload.get("recursive", False))
        limit = max(1, min(int(payload.get("limit", 200)), 1000))
        iterator = base.rglob("*") if recursive else base.iterdir()

        results: list[str] = []
        for candidate in sorted(iterator, key=lambda item: item.as_posix().lower()):
            try:
                resolved = self._workspace.resolve(str(candidate), must_exist=True)
            except WorkspaceBoundaryError:
                continue
            display = self._workspace.display(resolved)
            results.append(display + ("/" if resolved.is_dir() else ""))
            if len(results) >= limit:
                break
        return "\n".join(results) if results else "Directory is empty"

    def _check_size(self, path: Path) -> None:
        size = path.stat().st_size
        if size > self._max_file_size_bytes:
            raise ValueError(
                f"File size ({size} bytes) exceeds maximum allowed size ({self._max_file_size_bytes} bytes)"
            )

    @staticmethod
    def _read_text(path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8", "gbk", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1")

    @staticmethod
    def _format_lines(lines: list[str], start_line: int) -> str:
        result: list[str] = []
        max_line_length = 10_000
        for index, line in enumerate(lines, start=start_line):
            if len(line) <= max_line_length:
                result.append(f"{index:6d}\t{line}")
                continue
            for chunk_index, start in enumerate(range(0, len(line), max_line_length)):
                chunk = line[start : start + max_line_length]
                label = f"{index:6d}" if chunk_index == 0 else f"{index}.{chunk_index: <4}"
                result.append(f"{label}\t{chunk}")
        return "\n".join(result)
