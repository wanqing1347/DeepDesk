import asyncio

from app.api_schemas import FileContentVO, FileInfoVO
from app.tools.file_content import FileContentTool


class StubFileService:
    def __init__(self, info: FileInfoVO, content: str = "small content") -> None:
        self.info = info
        self.content = content

    def get_info(self, file_id: str) -> FileInfoVO:
        if file_id != self.info.file_id:
            raise ValueError(f"文件不存在: {file_id}")
        return self.info

    def get_content(self, file_id: str) -> FileContentVO:
        if file_id != self.info.file_id:
            raise ValueError(f"文件不存在: {file_id}")
        return FileContentVO(content=self.content, length=len(self.content))


class StubRagService:
    def __init__(self, results: list[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.results = results or ["segment one", "segment two"]

    async def retrieve(self, *, file_id: str, question: str) -> list[str]:
        self.calls.append((file_id, question))
        return self.results


def _info(*, embed: int, status: str = "SUCCESS") -> FileInfoVO:
    return FileInfoVO(
        fileId="file-1",
        fileName="demo.txt",
        fileType="txt",
        fileSize=12,
        status=status,
        embed=embed,
    )


def test_small_file_tool_loads_direct_content_with_standard_response_format() -> None:
    tool = FileContentTool(StubFileService(_info(embed=0), "hello document"), None)  # type: ignore[arg-type]

    result = asyncio.run(tool.call('{"fileId":"file-1","question":"what?"}'))

    assert result == (
        "=== 文件信息 ===\n"
        "文件名: demo.txt\n"
        "文件类型: txt\n"
        "\n"
        "=== 文件内容 ===\n"
        "hello document"
    )


def test_large_file_tool_uses_rag_and_preserves_segment_order() -> None:
    rag = StubRagService()
    tool = FileContentTool(StubFileService(_info(embed=1)), rag)  # type: ignore[arg-type]

    result = asyncio.run(tool.call('{"fileId":"file-1","question":"find answer"}'))

    assert rag.calls == [("file-1", "find answer")]
    assert result == (
        "=== 文件信息 ===\n"
        "文件名: demo.txt\n"
        "文件类型: txt\n"
        "\n"
        "=== 文件内容 ===\n"
        "相关内容: \n"
        "\n"
        "segment one\n"
        "\n"
        "segment two\n"
        "\n"
    )


def test_large_file_tool_requires_question_before_rag() -> None:
    rag = StubRagService()
    tool = FileContentTool(StubFileService(_info(embed=1)), rag)  # type: ignore[arg-type]

    result = asyncio.run(tool.call('{"fileId":"file-1","question":""}'))

    assert rag.calls == []
    assert "请提供具体问题以进行语义检索。" in result


def test_large_file_tool_falls_back_to_saved_text_when_pgvector_retrieval_fails() -> None:
    rag = StubRagService(["RAG 检索失败: pgvector unavailable"])
    tool = FileContentTool(
        StubFileService(_info(embed=1), "saved extracted text"),
        rag,
    )  # type: ignore[arg-type]

    result = asyncio.run(tool.call('{"fileId":"file-1","question":"find answer"}'))

    assert rag.calls == [("file-1", "find answer")]
    assert "RAG 检索暂时不可用" in result
    assert "saved extracted text" in result
    assert "pgvector unavailable" not in result


def test_large_file_tool_falls_back_to_saved_text_when_rag_service_is_not_configured() -> None:
    tool = FileContentTool(
        StubFileService(_info(embed=1), "saved extracted text"),
        None,
    )  # type: ignore[arg-type]

    result = asyncio.run(tool.call('{"fileId":"file-1","question":"find answer"}'))

    assert "RAG 检索服务不可用" in result
    assert "saved extracted text" in result


def test_file_tool_reports_invalid_or_unavailable_files_without_raising() -> None:
    tool = FileContentTool(StubFileService(_info(embed=0, status="PROCESSING")), None)  # type: ignore[arg-type]

    processing = asyncio.run(tool.call('{"fileId":"file-1","question":"q"}'))
    missing = asyncio.run(tool.call('{"fileId":"missing","question":"q"}'))
    malformed = asyncio.run(tool.call("not-json"))

    assert "当前状态: PROCESSING" in processing
    assert missing == "文件不存在: missing"
    assert malformed == "工具参数格式错误"
