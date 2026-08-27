import asyncio
import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config import Settings
from ..providers.llm import OpenAICompatibleClient
from ..providers.retry import is_retryable_http_error, sleep_before_retry_sync
from ..tracing import inject_trace_headers, trace_provider_call


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class QueryRewriter(Protocol):
    async def compress(self, question: str) -> str: ...

    async def expand(self, query: str, count: int) -> list[str]: ...


@dataclass(slots=True, frozen=True)
class VectorHit:
    document_id: str
    content: str
    score: float | None = None
    metadata: dict[str, object] | None = None


class VectorStore(Protocol):
    def add(self, *, file_id: str, chunks: list[str], embeddings: list[list[float]]) -> None: ...

    def search(self, *, file_id: str, embedding: list[float], top_k: int) -> list[VectorHit]: ...

    def delete(self, *, file_id: str) -> None: ...


class ParagraphOverlapSplitter:
    """Paragraph splitter with overlap support."""

    def __init__(self, chunk_size: int = 500, overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if overlap < 0:
            raise ValueError("overlap 不能为负数")
        if overlap >= chunk_size:
            raise ValueError("overlap 不能大于等于 chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap

    def split(self, content: str) -> list[str]:
        if not content or not content.strip():
            return []

        chunks: list[str] = []
        current = ""
        for paragraph in re.split(r"\n+", content):
            if not paragraph or not paragraph.strip():
                continue

            start = 0
            while start < len(paragraph):
                remaining_space = self._chunk_size - len(current)
                end = min(start + remaining_space, len(paragraph))
                current += paragraph[start:end]

                if len(current) >= self._chunk_size:
                    chunks.append(current)
                    overlap_text = current[-self._overlap :] if self._overlap > 0 else ""
                    current = overlap_text

                start = end

        if current:
            chunks.append(current)
        return chunks


class DashScopeEmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("transport and client cannot both be provided")
        self._settings = settings
        self._transport = transport
        self._client = client

    @contextmanager
    def _client_scope(self):
        if self._client is not None:
            yield self._client
            return
        with httpx.Client(
            timeout=self._settings.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            yield client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = self._settings.embedding_provider_api_key
        base_url = self._settings.embedding_provider_base_url
        if not api_key:
            raise RuntimeError("EMBEDDING_API_KEY/OPENAI_API_KEY 未配置，无法生成 embedding")
        if not base_url:
            raise RuntimeError("EMBEDDING_BASE_URL/OPENAI_BASE_URL 未配置，无法生成 embedding")

        url = base_url.rstrip("/") + "/embeddings"
        payload = {
            "model": self._settings.embedding_model,
            "input": texts,
            "dimensions": self._settings.embedding_dimension,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        with trace_provider_call("embedding", "embed"):
            traced_headers = inject_trace_headers(headers)
            with self._client_scope() as client:
                for attempt in range(self._settings.provider_max_retries + 1):
                    try:
                        response = client.post(url, headers=traced_headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        break
                    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                        if attempt >= self._settings.provider_max_retries or not is_retryable_http_error(exc):
                            raise
                        sleep_before_retry_sync(
                            retry_number=attempt + 1,
                            base_seconds=self._settings.provider_retry_base_seconds,
                            max_seconds=self._settings.provider_retry_max_seconds,
                            provider="embedding",
                            operation="embed",
                        )
                else:
                    raise RuntimeError("embedding request retry loop exited unexpectedly")

        raw_items = data.get("data") or []
        ordered = sorted(raw_items, key=lambda item: int(item.get("index", 0)))
        embeddings = [list(map(float, item.get("embedding") or [])) for item in ordered]
        if len(embeddings) != len(texts):
            raise RuntimeError(f"embedding 数量不匹配: expected={len(texts)}, actual={len(embeddings)}")
        for embedding in embeddings:
            if len(embedding) != self._settings.embedding_dimension:
                raise RuntimeError(
                    f"embedding 维度不匹配: expected={self._settings.embedding_dimension}, actual={len(embedding)}"
                )
        return embeddings


class OpenAIQueryRewriter:
    def __init__(self, settings: Settings, llm_client: OpenAICompatibleClient | None = None) -> None:
        self._llm = llm_client or OpenAICompatibleClient(
            settings,
            api_key=settings.query_rewrite_provider_api_key,
            base_url=settings.query_rewrite_provider_base_url,
            model=settings.query_rewrite_provider_model,
        )

    async def compress(self, question: str) -> str:
        response = await self._llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "你是检索查询压缩器。将用户问题压缩为一个适合语义向量检索的独立查询，"
                        "保留关键实体、数字、时间和限定条件。只输出压缩后的查询文本。"
                    ),
                },
                {"role": "user", "content": question},
            ],
            [],
        )
        compressed = _assistant_text(response).strip()
        return compressed or question

    async def expand(self, query: str, count: int) -> list[str]:
        response = await self._llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"你是语义检索查询扩展器。基于输入查询生成 {count} 个含义相近但措辞不同的查询。"
                        "必须只输出 JSON 字符串数组，不要 Markdown，不要解释。"
                    ),
                },
                {"role": "user", "content": query},
            ],
            [],
        )
        candidates = _json_string_array(_assistant_text(response))
        results: list[str] = []
        for candidate in candidates:
            normalized = candidate.strip()
            if normalized and normalized != query and normalized not in results:
                results.append(normalized)
            if len(results) >= count:
                break
        return results


class PgVectorFileStore:
    """Spring AI PgVectorStore-compatible table adapter for vector_file_info."""

    _VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        *,
        database_url: str,
        table_name: str,
        dimensions: int,
        connect_timeout_seconds: int = 5,
    ) -> None:
        if not database_url:
            raise ValueError("VECTOR_DATABASE_URL 未配置")
        if not self._VALID_IDENTIFIER.fullmatch(table_name):
            raise ValueError(f"非法向量表名: {table_name}")
        self._table_name = table_name
        self._dimensions = dimensions
        self._engine = self._build_engine(database_url, connect_timeout_seconds)
        self._initialized = False

    @staticmethod
    def _build_engine(database_url: str, connect_timeout_seconds: int) -> Engine:
        normalized = database_url
        if normalized.startswith("postgres://"):
            normalized = "postgresql+psycopg://" + normalized.removeprefix("postgres://")
        elif normalized.startswith("postgresql://"):
            normalized = "postgresql+psycopg://" + normalized.removeprefix("postgresql://")
        return create_engine(
            normalized,
            pool_pre_ping=True,
            connect_args={"connect_timeout": max(1, connect_timeout_seconds)},
        )

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        table = self._table_name
        index_name = f"{table}_embedding_idx"
        with self._engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS hstore"))
            connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            connection.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
                        content text,
                        metadata json,
                        embedding vector({self._dimensions})
                    )
                    """
                )
            )
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table} USING hnsw (embedding vector_cosine_ops)"
                )
            )
        self._initialized = True

    def add(self, *, file_id: str, chunks: list[str], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks 与 embeddings 数量不一致")
        self._ensure_schema()
        self.delete(file_id=file_id)
        if not chunks:
            return

        statement = text(
            f"""
            INSERT INTO {self._table_name} (id, content, metadata, embedding)
            VALUES (:id, :content, CAST(:metadata AS json), CAST(:embedding AS vector))
            """
        )
        rows = [
            {
                "id": str(uuid.uuid4()),
                "content": chunk,
                "metadata": json.dumps({"fileid": file_id, "chunkId": index}, ensure_ascii=False),
                "embedding": _vector_literal(embedding),
            }
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]
        with self._engine.begin() as connection:
            connection.execute(statement, rows)

    def search(self, *, file_id: str, embedding: list[float], top_k: int) -> list[VectorHit]:
        self._ensure_schema()
        statement = text(
            f"""
            SELECT
                id::text AS id,
                content,
                metadata,
                1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM {self._table_name}
            WHERE metadata->>'fileid' = :file_id
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {"file_id": file_id, "embedding": _vector_literal(embedding), "top_k": top_k},
            )
            results: list[VectorHit] = []
            for row in rows:
                raw_metadata = row.metadata
                metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else None
                raw_score = row.score
                score = float(raw_score) if raw_score is not None else None
                results.append(
                    VectorHit(
                        document_id=str(row.id),
                        content=str(row.content or ""),
                        score=score,
                        metadata=metadata,
                    )
                )
            return results

    def delete(self, *, file_id: str) -> None:
        self._ensure_schema()
        with self._engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM {self._table_name} WHERE metadata->>'fileid' = :file_id"),
                {"file_id": file_id},
            )

    def check_ready(self) -> None:
        # Readiness must not create extensions/tables. Schema initialization stays
        # on the real index/search path; the probe only verifies connectivity.
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self._engine.dispose()


class FileRagService:
    def __init__(
        self,
        settings: Settings,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        query_rewriter: QueryRewriter,
    ) -> None:
        self._settings = settings
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._query_rewriter = query_rewriter
        self._splitter = ParagraphOverlapSplitter(
            settings.file_chunk_size_chars,
            settings.file_chunk_overlap_chars,
        )

    def index(self, *, file_id: str, text: str) -> bool:
        chunks = self._splitter.split(text)
        if not chunks:
            return False

        embeddings: list[list[float]] = []
        batch_size = self._settings.embedding_batch_size
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            batch_embeddings = self._embedding_provider.embed(batch)
            if len(batch_embeddings) != len(batch):
                raise RuntimeError("embedding provider 返回数量与 batch 不一致")
            embeddings.extend(batch_embeddings)

        for embedding in embeddings:
            if len(embedding) != self._settings.embedding_dimension:
                raise RuntimeError(
                    f"embedding 维度不匹配: expected={self._settings.embedding_dimension}, actual={len(embedding)}"
                )

        self._vector_store.add(file_id=file_id, chunks=chunks, embeddings=embeddings)
        return True

    def delete(self, *, file_id: str) -> None:
        self._vector_store.delete(file_id=file_id)

    def check_ready(self) -> None:
        check_ready = getattr(self._vector_store, "check_ready", None)
        if callable(check_ready):
            check_ready()

    def dispose(self) -> None:
        dispose = getattr(self._vector_store, "dispose", None)
        if callable(dispose):
            dispose()

    async def retrieve(self, *, file_id: str, question: str) -> list[str]:
        if not file_id.strip() or not question.strip():
            return ["检索参数不能为空"]

        try:
            compressed = await self._query_rewriter.compress(question)
            expanded = await self._query_rewriter.expand(compressed, self._settings.rag_multi_query_count)
            queries = [compressed, *expanded]
            return await asyncio.to_thread(self._retrieve_sync, file_id, queries)
        except Exception as exc:
            return [f"RAG 检索失败: {exc}"]

    def _retrieve_sync(self, file_id: str, queries: list[str]) -> list[str]:
        results: list[str] = []
        seen_ids: set[str] = set()
        for query in queries:
            embeddings = self._embedding_provider.embed([query])
            if not embeddings:
                continue
            for hit in self._vector_store.search(
                file_id=file_id,
                embedding=embeddings[0],
                top_k=self._settings.rag_top_k,
            ):
                if hit.document_id in seen_ids:
                    continue
                seen_ids.add(hit.document_id)
                results.append(hit.content)
        return results


def build_file_rag_service(
    settings: Settings,
    *,
    llm_client: OpenAICompatibleClient | None = None,
    provider_async_http_client: httpx.AsyncClient | None = None,
    provider_http_client: httpx.Client | None = None,
) -> FileRagService | None:
    if not settings.vector_database_url:
        return None
    has_query_rewrite_override = any(
        (
            settings.query_rewrite_api_key.strip(),
            settings.query_rewrite_base_url.strip(),
            settings.query_rewrite_model.strip(),
        )
    )
    query_llm_client = llm_client
    if query_llm_client is None or has_query_rewrite_override:
        query_llm_client = OpenAICompatibleClient(
            settings,
            client=provider_async_http_client,
            api_key=settings.query_rewrite_provider_api_key,
            base_url=settings.query_rewrite_provider_base_url,
            model=settings.query_rewrite_provider_model,
        )

    return FileRagService(
        settings,
        embedding_provider=DashScopeEmbeddingClient(settings, client=provider_http_client),
        vector_store=PgVectorFileStore(
            database_url=settings.vector_database_url,
            table_name=settings.vector_table_name,
            dimensions=settings.embedding_dimension,
            connect_timeout_seconds=settings.vector_connect_timeout_seconds,
        ),
        query_rewriter=OpenAIQueryRewriter(settings, llm_client=query_llm_client),
    )


def _assistant_text(response: dict[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return str(content or "")


def _json_string_array(content: str) -> list[str]:
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("[")
        end = candidate.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            value = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(format(value, ".17g") for value in embedding) + "]"
