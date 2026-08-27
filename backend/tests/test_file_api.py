from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.files.parser import FileParser
from app.files.service import FileService
from app.persistence import Base, Database
from app.routers.file import build_file_router


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def upload(self, *, object_name: str, content: bytes, content_type: str) -> str:
        self.objects[object_name] = content
        return f"http://minio.test/rag-test2/{object_name}"

    def delete(self, object_name: str) -> None:
        self.deleted.append(object_name)
        self.objects.pop(object_name, None)


class FailingUploadObjectStore(FakeObjectStore):
    def upload(self, *, object_name: str, content: bytes, content_type: str) -> str:
        raise RuntimeError("minio unavailable")


class FailingDeleteObjectStore(FakeObjectStore):
    def delete(self, object_name: str) -> None:
        raise RuntimeError("minio unavailable")


class FakeImageDescriber:
    def describe(self, *, content: bytes, content_type: str) -> str:
        return f"image:{content_type}:{len(content)}"


class FakeVectorIndexer:
    def __init__(self) -> None:
        self.indexed: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def index(self, *, file_id: str, text: str) -> bool:
        self.indexed.append((file_id, text))
        return True

    def delete(self, *, file_id: str) -> None:
        self.deleted.append(file_id)


class FailingVectorIndexer(FakeVectorIndexer):
    def index(self, *, file_id: str, text: str) -> bool:
        self.indexed.append((file_id, text))
        raise RuntimeError("pgvector unavailable")


class FailingDeleteVectorIndexer(FakeVectorIndexer):
    def delete(self, *, file_id: str) -> None:
        raise RuntimeError("pgvector unavailable")


def _build_app(*, max_file_size: int = 1024, large_threshold: int = 5000) -> tuple[
    FastAPI,
    Database,
    FakeObjectStore,
    FakeVectorIndexer,
]:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
        max_file_size_bytes=max_file_size,
        large_file_threshold_chars=large_threshold,
        max_extracted_text_chars=20000,
    )
    object_store = FakeObjectStore()
    vector_indexer = FakeVectorIndexer()
    service = FileService(
        settings,
        database.session_factory,
        object_store=object_store,
        parser=FileParser(max_text_chars=settings.max_extracted_text_chars),
        image_describer=FakeImageDescriber(),
        vector_indexer=vector_indexer,
    )

    def get_service() -> FileService:
        return service

    app = FastAPI()
    app.include_router(build_file_router(get_service))
    return app, database, object_store, vector_indexer


def test_file_api_text_upload_read_list_exists_and_delete_contract() -> None:
    app, _, object_store, vector_indexer = _build_app()

    with TestClient(app) as client:
        upload = client.post(
            "/file/upload",
            files={"file": ("notes.txt", b"hello file rag", "text/plain")},
        )
        payload = upload.json()
        assert payload["code"] == 200
        assert payload["message"] == ""
        info = payload["data"]
        file_id = info["fileId"]
        assert info["fileName"] == "notes.txt"
        assert info["fileType"] == "txt"
        assert info["fileSize"] == len(b"hello file rag")
        assert info["status"] == "SUCCESS"
        assert info["embed"] == 0
        assert info["extractedText"] == "hello file rag"
        assert info["minioPath"].endswith(f"file-{file_id.replace('-', '')}.txt")

        detail = client.get(f"/file/info/{file_id}").json()
        assert detail["code"] == 200
        assert detail["data"]["fileId"] == file_id

        content = client.get(f"/file/content/{file_id}").json()
        assert content == {"code": 200, "message": "", "data": {"content": "hello file rag", "length": 14}}

        exists = client.get(f"/file/exists/{file_id}").json()
        assert exists == {"code": 200, "message": "", "data": True}

        listing = client.get("/file/list").json()
        assert listing["code"] == 200
        assert listing["data"]["count"] == 1
        assert listing["data"]["files"][file_id]["fileName"] == "notes.txt"

        deleted = client.delete(f"/file/{file_id}").json()
        assert deleted == {"code": 200, "message": "文件删除成功", "data": None}
        assert client.get(f"/file/exists/{file_id}").json()["data"] is False

    object_name = f"file-{file_id.replace('-', '')}.txt"
    assert object_name not in object_store.objects
    assert object_store.deleted == [object_name]
    assert vector_indexer.deleted == []


def test_file_api_large_text_sets_embed_and_deletes_vectors() -> None:
    app, _, _, vector_indexer = _build_app(large_threshold=10)
    full_text = "0123456789 large document"

    with TestClient(app) as client:
        upload = client.post(
            "/file/upload",
            files={"file": ("large.txt", full_text.encode(), "text/plain")},
        ).json()
        file_id = upload["data"]["fileId"]
        assert upload["data"]["embed"] == 1
        assert vector_indexer.indexed == [(file_id, full_text)]

        deleted = client.delete(f"/file/{file_id}").json()
        assert deleted["code"] == 200

    assert vector_indexer.deleted == [file_id]


def test_minio_upload_failure_marks_metadata_failed_instead_of_reporting_success() -> None:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
    )
    service = FileService(
        settings,
        database.session_factory,
        object_store=FailingUploadObjectStore(),
        parser=FileParser(),
        image_describer=FakeImageDescriber(),
        vector_indexer=FakeVectorIndexer(),
    )

    try:
        service.upload(
            file_name="notes.txt",
            content=b"hello",
            content_type="text/plain",
        )
    except RuntimeError as exc:
        assert "minio unavailable" in str(exc)
    else:
        raise AssertionError("MinIO failure must not be reported as a successful upload")

    listing = service.list_files()
    assert listing.count == 1
    failed = next(iter(listing.files.values()))
    assert failed.status == "FAILED"
    assert failed.embed == 0


def test_minio_delete_failure_keeps_metadata_in_direct_text_fallback_state() -> None:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
        large_file_threshold_chars=5,
    )
    object_store = FailingDeleteObjectStore()
    vector_indexer = FakeVectorIndexer()
    service = FileService(
        settings,
        database.session_factory,
        object_store=object_store,
        parser=FileParser(),
        image_describer=FakeImageDescriber(),
        vector_indexer=vector_indexer,
    )
    info = service.upload(
        file_name="large.txt",
        content=b"0123456789",
        content_type="text/plain",
    )
    assert info.embed == 1

    try:
        service.delete(info.file_id)
    except RuntimeError as exc:
        assert "minio unavailable" in str(exc)
    else:
        raise AssertionError("MinIO delete failure must not delete metadata")

    assert service.exists(info.file_id) is True
    assert vector_indexer.deleted == [info.file_id]
    assert service.get_info(info.file_id).embed == 0
    assert service.get_content(info.file_id).content == "0123456789"


def test_pgvector_delete_failure_aborts_before_minio_or_metadata_are_deleted() -> None:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
        large_file_threshold_chars=5,
    )
    object_store = FakeObjectStore()
    vector_indexer = FailingDeleteVectorIndexer()
    service = FileService(
        settings,
        database.session_factory,
        object_store=object_store,
        parser=FileParser(),
        image_describer=FakeImageDescriber(),
        vector_indexer=vector_indexer,
    )
    info = service.upload(
        file_name="large.txt",
        content=b"0123456789",
        content_type="text/plain",
    )
    object_name = f"file-{info.file_id.replace('-', '')}.txt"
    assert object_name in object_store.objects

    try:
        service.delete(info.file_id)
    except RuntimeError as exc:
        assert "pgvector unavailable" in str(exc)
    else:
        raise AssertionError("PgVector delete failure must abort the delete operation")

    assert service.exists(info.file_id) is True
    assert service.get_info(info.file_id).embed == 1
    assert object_name in object_store.objects
    assert object_store.deleted == []


def test_large_file_embedding_failure_keeps_upload_successful_with_embed_zero() -> None:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
        large_file_threshold_chars=10,
    )
    object_store = FakeObjectStore()
    vector_indexer = FailingVectorIndexer()
    service = FileService(
        settings,
        database.session_factory,
        object_store=object_store,
        parser=FileParser(),
        image_describer=FakeImageDescriber(),
        vector_indexer=vector_indexer,
    )

    info = service.upload(
        file_name="large.txt",
        content=b"0123456789",
        content_type="text/plain",
    )

    assert info.status == "SUCCESS"
    assert info.embed == 0
    assert vector_indexer.indexed == [(info.file_id, "0123456789")]


def test_unsupported_doc_upload_marks_metadata_failed_after_minio_upload() -> None:
    app, _, object_store, _ = _build_app()

    with TestClient(app) as client:
        upload = client.post(
            "/file/upload",
            files={"file": ("legacy.doc", b"legacy-doc", "application/msword")},
        ).json()
        listing = client.get("/file/list").json()

    assert upload["code"] == 500
    assert "暂不支持 .doc 格式" in upload["message"]
    assert listing["data"]["count"] == 1
    failed = next(iter(listing["data"]["files"].values()))
    assert failed["status"] == "FAILED"
    assert failed["embed"] == 0
    assert len(object_store.objects) == 1


def test_file_api_image_uses_multimodal_description() -> None:
    app, _, _, _ = _build_app()

    with TestClient(app) as client:
        upload = client.post(
            "/file/upload",
            files={"file": ("photo.png", b"fake-png", "image/png")},
        ).json()

    assert upload["code"] == 200
    assert upload["data"]["status"] == "SUCCESS"
    assert upload["data"]["extractedText"] == "image:image/png:8"


def test_file_api_rejects_oversized_upload_without_creating_metadata() -> None:
    app, database, object_store, _ = _build_app(max_file_size=4)

    with TestClient(app) as client:
        upload = client.post(
            "/file/upload",
            files={"file": ("too-big.txt", b"12345", "text/plain")},
        ).json()
        listing = client.get("/file/list").json()

    assert upload["code"] == 500
    assert "文件大小不能超过50MB" in upload["message"]
    assert listing["data"]["count"] == 0
    assert object_store.objects == {}

    with database.session_factory() as session:
        assert session.query(Base.metadata.tables["ai_file_info"]).count() == 0


def test_file_router_is_registered_in_main_app_even_without_database() -> None:
    from app.main import create_app

    app = create_app(Settings(persistence_mode="memory"))
    with TestClient(app) as client:
        response = client.get("/file/list")

    assert response.status_code == 503
    assert response.json()["detail"] == "文件持久化未启用，请设置 PERSISTENCE_MODE=database"
