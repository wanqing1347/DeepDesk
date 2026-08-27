import asyncio
import json
from typing import Any, ClassVar

from ..files.rag import FileRagService
from ..files.service import FileService


class FileContentTool:
    name = "loadContent"
    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "根据文件ID加载文件内容或进行RAG语义检索。如果文件已向量化(embed=1)则使用语义搜索返回相关片段，"
                "否则直接返回完整文件内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fileId": {"type": "string", "description": "文件ID"},
                    "question": {"type": "string", "description": "用户的问题，用于语义检索（可选）"},
                },
                "required": ["fileId", "question"],
            },
        },
    }

    def __init__(self, file_service: FileService, rag_service: FileRagService | None) -> None:
        self._file_service = file_service
        self._rag_service = rag_service

    async def call(self, arguments: str) -> str:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "工具参数格式错误"
        if not isinstance(payload, dict):
            return "工具参数格式错误"

        file_id = str(payload.get("fileId") or "").strip()
        question = str(payload.get("question") or "").strip()
        if not file_id:
            return "文件ID不能为空"

        try:
            info = await asyncio.to_thread(self._file_service.get_info, file_id)
            if info.status != "SUCCESS":
                return f"文件处理中或处理失败，当前状态: {info.status}，文件ID: {file_id}"

            if info.embed == 1:
                return await self._retrieve_with_rag(file_id, info.file_name, info.file_type, question)
            return await self._load_directly(file_id, info.file_name, info.file_type)
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            return f"加载文件内容失败: {exc}"

    async def _retrieve_with_rag(
        self,
        file_id: str,
        file_name: str,
        file_type: str | None,
        question: str,
    ) -> str:
        if not question:
            return self._build_response(file_name, file_type, "请提供具体问题以进行语义检索。")
        if self._rag_service is None:
            return await self._load_directly(
                file_id,
                file_name,
                file_type,
                notice="RAG 检索服务不可用，已降级为数据库中保存的文件文本。",
            )

        results = await self._rag_service.retrieve(file_id=file_id, question=question)
        if len(results) == 1 and results[0].startswith("RAG 检索失败:"):
            return await self._load_directly(
                file_id,
                file_name,
                file_type,
                notice="RAG 检索暂时不可用，已降级为数据库中保存的文件文本。",
            )
        if not results:
            return self._build_response(file_name, file_type, "未检索到与问题相关的内容")
        return self._build_response(file_name, file_type, "RAG检索", results)

    async def _load_directly(
        self,
        file_id: str,
        file_name: str,
        file_type: str | None,
        *,
        notice: str | None = None,
    ) -> str:
        content = await asyncio.to_thread(self._file_service.get_content, file_id)
        text = content.content.strip() or "该文件没有可识别的内容"
        if notice:
            text = f"{notice}\n\n{text}"
        return self._build_response(file_name, file_type, text)

    @staticmethod
    def _build_response(
        file_name: str,
        file_type: str | None,
        content: str,
        segments: list[str] | None = None,
    ) -> str:
        parts = [
            "=== 文件信息 ===",
            f"文件名: {file_name}",
            f"文件类型: {file_type or ''}",
            "",
            "=== 文件内容 ===",
        ]
        if segments:
            parts.extend(["相关内容: ", ""])
            for segment in segments:
                parts.extend([segment, ""])
            # Keep a blank line after every RAG segment for readable tool context,
            # including the final segment. Keep the exact Tool context shape.
            return "\n".join(parts) + "\n"
        parts.append(content)
        return "\n".join(parts)
