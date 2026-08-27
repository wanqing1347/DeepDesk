import asyncio

import pytest

import app.files.rag as rag_module
from app.config import Settings
from app.files.rag import FileRagService, ParagraphOverlapSplitter, PgVectorFileStore, VectorHit


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(index + 1)] * self.dimensions for index, _ in enumerate(texts)]


class FakeVectorStore:
    def __init__(self) -> None:
        self.added: tuple[str, list[str], list[list[float]]] | None = None
        self.search_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.search_results: list[list[VectorHit]] = []

    def add(self, *, file_id: str, chunks: list[str], embeddings: list[list[float]]) -> None:
        self.added = (file_id, list(chunks), list(embeddings))

    def search(self, *, file_id: str, embedding: list[float], top_k: int) -> list[VectorHit]:
        self.search_calls.append((file_id, top_k))
        index = len(self.search_calls) - 1
        return self.search_results[index] if index < len(self.search_results) else []

    def delete(self, *, file_id: str) -> None:
        self.deleted.append(file_id)


class FakeQueryRewriter:
    def __init__(self) -> None:
        self.compressed_from: str | None = None
        self.expanded_from: tuple[str, int] | None = None

    async def compress(self, question: str) -> str:
        self.compressed_from = question
        return "compressed query"

    async def expand(self, query: str, count: int) -> list[str]:
        self.expanded_from = (query, count)
        return ["expanded 1", "expanded 2", "expanded 3"]


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "file_chunk_size_chars": 10,
        "file_chunk_overlap_chars": 0,
        "embedding_batch_size": 9,
        "embedding_dimension": 3,
        "rag_top_k": 5,
        "rag_multi_query_count": 3,
    }
    values.update(overrides)
    return Settings(**values)


def test_paragraph_overlap_splitter_preserves_fill_and_overlap_behavior() -> None:
    splitter = ParagraphOverlapSplitter(chunk_size=5, overlap=2)

    assert splitter.split("abc\n\ndefgh") == ["abcde", "defgh", "gh"]
    assert splitter.split("  \n\n") == []


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (5, -1), (5, 5), (5, 6)],
)
def test_splitter_rejects_invalid_parameters(chunk_size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ParagraphOverlapSplitter(chunk_size=chunk_size, overlap=overlap)


def test_index_uses_500_50_style_splitter_settings_and_embedding_batches_of_nine() -> None:
    settings = _settings()
    embedding = FakeEmbeddingProvider(dimensions=3)
    vector_store = FakeVectorStore()
    rag = FileRagService(
        settings,
        embedding_provider=embedding,
        vector_store=vector_store,
        query_rewriter=FakeQueryRewriter(),
    )

    assert rag.index(file_id="file-1", text="x" * 95) is True

    assert [len(batch) for batch in embedding.calls] == [9, 1]
    assert vector_store.added is not None
    file_id, chunks, embeddings = vector_store.added
    assert file_id == "file-1"
    assert len(chunks) == 10
    assert chunks[:2] == ["x" * 10, "x" * 10]
    assert chunks[-1] == "x" * 5
    assert len(embeddings) == 10
    assert all(len(item) == 3 for item in embeddings)


def test_retrieve_compresses_expands_to_three_plus_original_topk5_and_filters_fileid() -> None:
    settings = _settings()
    embedding = FakeEmbeddingProvider(dimensions=3)
    vector_store = FakeVectorStore()
    vector_store.search_results = [
        [VectorHit("doc-1", "first"), VectorHit("doc-2", "second")],
        [VectorHit("doc-2", "second duplicate"), VectorHit("doc-3", "third")],
        [],
        [VectorHit("doc-4", "fourth")],
    ]
    rewriter = FakeQueryRewriter()
    rag = FileRagService(
        settings,
        embedding_provider=embedding,
        vector_store=vector_store,
        query_rewriter=rewriter,
    )

    results = asyncio.run(rag.retrieve(file_id="file-42", question="original question"))

    assert rewriter.compressed_from == "original question"
    assert rewriter.expanded_from == ("compressed query", 3)
    assert embedding.calls == [["compressed query"], ["expanded 1"], ["expanded 2"], ["expanded 3"]]
    assert vector_store.search_calls == [("file-42", 5)] * 4
    assert results == ["first", "second", "third", "fourth"]


def test_retrieve_blank_parameters_returns_expected_failure_message() -> None:
    rag = FileRagService(
        _settings(),
        embedding_provider=FakeEmbeddingProvider(dimensions=3),
        vector_store=FakeVectorStore(),
        query_rewriter=FakeQueryRewriter(),
    )

    assert asyncio.run(rag.retrieve(file_id="", question="q")) == ["检索参数不能为空"]
    assert asyncio.run(rag.retrieve(file_id="file", question=" ")) == ["检索参数不能为空"]


def test_delete_delegates_fileid_filter_to_vector_store() -> None:
    vector_store = FakeVectorStore()
    rag = FileRagService(
        _settings(),
        embedding_provider=FakeEmbeddingProvider(dimensions=3),
        vector_store=vector_store,
        query_rewriter=FakeQueryRewriter(),
    )

    rag.delete(file_id="file-delete")

    assert vector_store.deleted == ["file-delete"]


def test_pgvector_engine_uses_bounded_connection_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(rag_module, "create_engine", fake_create_engine)
    store = PgVectorFileStore(
        database_url="postgresql://user:pass@localhost/db",
        table_name="vector_file_info",
        dimensions=1024,
        connect_timeout_seconds=3,
    )

    assert store._engine is sentinel
    assert captured["url"] == "postgresql+psycopg://user:pass@localhost/db"
    assert captured["pool_pre_ping"] is True
    assert captured["connect_args"] == {"connect_timeout": 3}


def test_pgvector_table_name_is_validated_before_sql_construction() -> None:
    with pytest.raises(ValueError, match="非法向量表名"):
        PgVectorFileStore(
            database_url="postgresql+psycopg://user:pass@localhost/db",
            table_name="vector_file_info;drop table x",
            dimensions=1024,
        )
