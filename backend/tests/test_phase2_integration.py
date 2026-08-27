import asyncio
import base64
import os
import uuid
from contextlib import suppress

import pytest
from minio import Minio
from minio.error import S3Error

from app.config import Settings
from app.files.rag import DashScopeEmbeddingClient, OpenAIQueryRewriter, PgVectorFileStore
from app.files.storage import MinioObjectStore
from app.providers.multimodal import OpenAICompatibleImageDescriber

pytestmark = pytest.mark.integration


def _integration_settings() -> Settings:
    if os.getenv("RUN_PHASE2_INTEGRATION", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set RUN_PHASE2_INTEGRATION=1 to run real Phase 2 integration tests")
    return Settings()


def _require(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized or normalized == "replace-me":
        pytest.fail(f"{name} must be configured when RUN_PHASE2_INTEGRATION=1")
    return normalized


def test_real_minio_round_trip() -> None:
    settings = _integration_settings()
    endpoint = _require(settings.minio_endpoint, "MINIO_ENDPOINT")
    access_key = _require(settings.minio_access_key, "MINIO_ACCESS_KEY")
    secret_key = _require(settings.minio_secret_key, "MINIO_SECRET_KEY")
    object_name = f"phase2-integration-{uuid.uuid4().hex}.txt"
    payload = b"deepdesk-backend phase2 minio integration"

    store = MinioObjectStore(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
        public_read=settings.minio_public_read,
        connect_timeout_seconds=settings.minio_connect_timeout_seconds,
        read_timeout_seconds=settings.minio_read_timeout_seconds,
        max_retries=settings.minio_max_retries,
    )
    clean_endpoint = endpoint.removeprefix("http://").removeprefix("https://").rstrip("/")
    client = Minio(
        clean_endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=settings.minio_secure,
    )

    try:
        url = store.upload(object_name=object_name, content=payload, content_type="text/plain")
        assert url.endswith(f"/{settings.minio_bucket}/{object_name}")

        response = client.get_object(settings.minio_bucket, object_name)
        try:
            assert response.read() == payload
        finally:
            response.close()
            response.release_conn()

        store.delete(object_name)
        with pytest.raises(S3Error):
            client.stat_object(settings.minio_bucket, object_name)
    finally:
        with suppress(Exception):
            store.delete(object_name)


def test_real_pgvector_round_trip_with_fileid_filter() -> None:
    settings = _integration_settings()
    database_url = _require(settings.vector_database_url, "VECTOR_DATABASE_URL")
    file_id = f"phase2-integration-{uuid.uuid4().hex}"
    dimensions = settings.embedding_dimension
    first = [0.0] * dimensions
    second = [0.0] * dimensions
    first[0] = 1.0
    second[1] = 1.0

    store = PgVectorFileStore(
        database_url=database_url,
        table_name=settings.vector_table_name,
        dimensions=dimensions,
        connect_timeout_seconds=settings.vector_connect_timeout_seconds,
    )
    added = False
    try:
        store.add(
            file_id=file_id,
            chunks=["phase2-vector-first", "phase2-vector-second"],
            embeddings=[first, second],
        )
        added = True
        hits = store.search(file_id=file_id, embedding=first, top_k=1)
        assert len(hits) == 1
        assert hits[0].content == "phase2-vector-first"

        other_hits = store.search(file_id=f"{file_id}-other", embedding=first, top_k=5)
        assert other_hits == []
    finally:
        if added:
            store.delete(file_id=file_id)
        store.dispose()


def test_real_dashscope_embedding_v4_1024() -> None:
    settings = _integration_settings()
    _require(settings.embedding_provider_api_key, "EMBEDDING_API_KEY/OPENAI_API_KEY")
    _require(settings.embedding_provider_base_url, "EMBEDDING_BASE_URL/OPENAI_BASE_URL")

    embeddings = DashScopeEmbeddingClient(settings).embed(["deepdesk phase2 embedding integration"])

    assert len(embeddings) == 1
    assert len(embeddings[0]) == settings.embedding_dimension == 1024


def test_real_multimodal_image_description() -> None:
    settings = _integration_settings()
    _require(settings.vision_provider_api_key, "VISION_API_KEY/OPENAI_API_KEY")
    _require(settings.vision_provider_base_url, "VISION_BASE_URL/OPENAI_BASE_URL")
    _require(settings.vision_provider_model, "VISION_MODEL/IMAGE_MODEL")
    # DashScope multimodal models require both image dimensions to be > 10.
    # A 16x16 PNG keeps the fixture tiny while still exercising the real
    # OpenAI-compatible multimodal request path end to end.
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAIUlEQVR4nGP8z0AaYCJRPcOoBmIAE1GqkMCoBmIAyaEEAEAuAR9UPEsJAAAAAElFTkSuQmCC"
    )

    description = OpenAICompatibleImageDescriber(settings).describe(content=image, content_type="image/png")

    assert description.strip()


def test_real_query_compression_and_multiquery_three() -> None:
    settings = _integration_settings()
    _require(settings.query_rewrite_provider_api_key, "QUERY_REWRITE_API_KEY/OPENAI_API_KEY")
    _require(settings.query_rewrite_provider_base_url, "QUERY_REWRITE_BASE_URL/OPENAI_BASE_URL")
    _require(settings.query_rewrite_provider_model, "QUERY_REWRITE_MODEL/OPENAI_MODEL")
    rewriter = OpenAIQueryRewriter(settings)

    compressed = asyncio.run(rewriter.compress("请告诉我附件里关于退款条件和退款时限分别是怎么规定的？"))
    expanded = asyncio.run(rewriter.expand(compressed, settings.rag_multi_query_count))

    assert compressed.strip()
    assert len(expanded) == settings.rag_multi_query_count == 3
    assert all(item.strip() and item != compressed for item in expanded)
