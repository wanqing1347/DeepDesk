"""Stable File RAG contract regression tests."""

import json
from difflib import SequenceMatcher
from pathlib import Path

from app.files.rag import ParagraphOverlapSplitter


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()


def _segment_similarity(left: str, right: str) -> float:
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _segment_coverage(expected: list[str], actual: list[str], threshold: float) -> float:
    if not expected:
        return 1.0
    matched = 0
    for segment in expected:
        best = max((_segment_similarity(segment, item) for item in actual), default=0.0)
        if best >= threshold:
            matched += 1
    return matched / len(expected)


def test_file_rag_splitter_is_deterministic() -> None:
    splitter = ParagraphOverlapSplitter(chunk_size=10, overlap=2)
    content = "abcdefghij\nklmnop"

    first = splitter.split(content)
    second = splitter.split(content)

    assert first == second
    assert first == ["abcdefghij", "ijklmnop"]
    assert first[1].startswith(first[0][-2:])


def test_segment_coverage_handles_partial_chunk_boundaries() -> None:
    expected = ["退款申请应在支付后七日内提出，审核通过后原路退回。", "会员权益不可转让。"]
    actual = ["说明：退款申请应在支付后七日内提出，审核通过后原路退回。其他条款如下。", "无关内容"]

    assert _segment_coverage(expected, actual, threshold=0.5) == 0.5


def test_file_rag_fixture_schema_keeps_core_retrieval_contract() -> None:
    schema_path = Path(__file__).parent / "golden" / "file-rag-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["title"] == "DeepDesk File RAG Regression Fixture v2"
    assert schema["properties"]["index"]["required"] == ["sourceText", "chunks", "embeddingInputs"]
    assert schema["properties"]["cases"]["items"]["required"] == ["name", "question", "expected"]
