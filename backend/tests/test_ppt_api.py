from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.persistence import Base, Database
from app.persistence.ppt_repository import PptRepository
from app.ppt.domain import PptStatus
from app.routers.ppt import build_ppt_router


def _build_app() -> tuple[FastAPI, Database, PptRepository]:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    repository = PptRepository(database.session_factory)

    def get_repository() -> PptRepository:
        return repository

    app = FastAPI()
    app.include_router(build_ppt_router(get_repository))
    return app, database, repository


def test_ppt_api_list_detail_and_delete_contract() -> None:
    app, database, repository = _build_app()
    first = repository.create_inst("conv-1", "Build the first deck")
    repository.update_file_url(
        first.id,
        "http://minio.test/rag-test2/ppt/conv-1/ppt_1_first.pptx",
        PptStatus.SUCCESS,
    )
    second = repository.create_inst("conv-2", "Build the second deck")
    repository.update_error(second.id, "render failed", PptStatus.FAILED)

    with TestClient(app) as client:
        listing = client.get("/ppt/list").json()
        assert listing["code"] == 200
        assert listing["data"]["count"] == 2
        assert [item["id"] for item in listing["data"]["presentations"]] == [second.id, first.id]

        ready = next(item for item in listing["data"]["presentations"] if item["id"] == first.id)
        assert ready["conversationId"] == "conv-1"
        assert ready["query"] == "Build the first deck"
        assert ready["status"] == "SUCCESS"
        assert ready["fileUrl"].endswith("ppt_1_first.pptx")

        detail = client.get(f"/ppt/{second.id}").json()
        assert detail["code"] == 200
        assert detail["data"]["conversationId"] == "conv-2"
        assert detail["data"]["status"] == "FAILED"
        assert detail["data"]["errorMsg"] == "render failed"

        deleted = client.delete(f"/ppt/{first.id}").json()
        assert deleted == {"code": 200, "message": "PPT删除成功", "data": None}
        assert repository.get_by_id(first.id) is None

        missing = client.get(f"/ppt/{first.id}").json()
        assert missing["code"] == 500
        assert missing["message"] == "PPT不存在"

        remaining = client.get("/ppt/list").json()
        assert remaining["data"]["count"] == 1
        assert remaining["data"]["presentations"][0]["id"] == second.id

    database.dispose()


def test_ppt_router_is_registered_in_main_app_even_without_database() -> None:
    from app.main import create_app

    app = create_app(Settings(persistence_mode="memory"))
    with TestClient(app) as client:
        response = client.get("/ppt/list")

    assert response.status_code == 503
    assert response.json()["detail"] == "PPT持久化未启用，请设置 PERSISTENCE_MODE=database"
