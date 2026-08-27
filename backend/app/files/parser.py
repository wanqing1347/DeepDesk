from dataclasses import dataclass
from io import BytesIO

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass(slots=True, frozen=True)
class ParseResult:
    full_text: str
    truncated_text: str


class FileParser:
    def __init__(self, *, max_text_chars: int = 20000) -> None:
        self._max_text_chars = max_text_chars

    def parse(self, *, file_name: str, content: bytes) -> ParseResult:
        file_type = self.file_type(file_name)
        if file_type == "pdf":
            full_text = self._parse_pdf(content)
        elif file_type == "docx":
            full_text = self._parse_docx(content)
        elif file_type == "doc":
            raise ValueError("暂不支持 .doc 格式，请转换为 .docx")
        elif file_type == "txt":
            full_text = self._parse_txt(content)
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")

        full_text = full_text.strip()
        if len(full_text) > self._max_text_chars:
            truncated = full_text[: self._max_text_chars] + "\n\n... (内容已截断，文件过长)"
        else:
            truncated = full_text
        return ParseResult(full_text=full_text, truncated_text=truncated)

    @staticmethod
    def file_type(file_name: str | None) -> str:
        if not file_name or "." not in file_name:
            return "unknown"
        stem, extension = file_name.rsplit(".", 1)
        if not stem or not extension:
            return "unknown"
        return extension.lower()

    @staticmethod
    def _parse_pdf(content: bytes) -> str:
        reader = PdfReader(BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    @staticmethod
    def _parse_docx(content: bytes) -> str:
        document = DocxDocument(BytesIO(content))
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text and paragraph.text.strip()]
        return "\n".join(paragraphs)

    @staticmethod
    def _parse_txt(content: bytes) -> str:
        return content.decode("utf-8").strip()
