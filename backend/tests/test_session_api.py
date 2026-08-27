from collections.abc import Iterator
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.persistence import AiFileInfo, AiPptInst, AiSession, Base, Database
from app.routers.session import build_session_router


def _build_app() -> tuple[FastAPI, Database]:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)

    def get_session() -> Iterator[Session]:
        yield from database.sessions()

    app = FastAPI()
    app.include_router(build_session_router(get_session))
    return app, database


def _seed(database: Database) -> None:
    now = datetime(2026, 8, 23, 12, 0, 0)
    with database.session_factory() as session:
        session.add_all(
            [
                AiSession(
                    session_id="conv-a",
                    agent_type="websearch",
                    question="第一问",
                    answer="第一答",
                    create_time=now,
                    update_time=now,
                ),
                AiSession(
                    session_id="conv-a",
                    agent_type="websearch",
                    question="第二问",
                    answer="第二答",
                    thinking="思考",
                    tools="web_search",
                    reference='{"type":"reference","content":[]}',
                    recommend='["继续问"]',
                    create_time=now + timedelta(minutes=1),
                    update_time=now + timedelta(minutes=2),
                ),
                AiSession(
                    session_id="conv-b",
                    agent_type="file",
                    question="文件问题",
                    answer="文件回答",
                    fileid="file-b",
                    create_time=now + timedelta(minutes=3),
                    update_time=now + timedelta(minutes=3),
                ),
                AiFileInfo(
                    file_id="file-a",
                    file_name="a.txt",
                    conversation_id="conv-a",
                    status="SUCCESS",
                ),
                AiPptInst(conversation_id="conv-a", status="INIT"),
            ]
        )
        session.commit()


def test_session_detail_matches_response_envelope_and_aliases() -> None:
    app, database = _build_app()
    _seed(database)

    with TestClient(app) as client:
        response = client.get("/session/conv-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["message"] == ""
    assert payload["data"]["conversationId"] == "conv-a"
    assert payload["data"]["agentType"] == "websearch"
    assert [message["question"] for message in payload["data"]["messages"]] == ["第一问", "第二问"]
    assert payload["data"]["messages"][1]["createTime"] is not None


def test_session_list_uses_static_route_and_first_record_semantics() -> None:
    app, database = _build_app()
    _seed(database)

    with TestClient(app) as client:
        response = client.get("/session/list?pageNum=1&pageSize=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["pageNum"] == 1
    assert payload["data"]["pageSize"] == 1
    assert payload["data"]["total"] == 2
    assert len(payload["data"]["records"]) == 1
    # The query selects the first record for each conversation, so conv-b
    # sorts ahead of conv-a because its first record has the newer update_time.
    assert payload["data"]["records"][0]["conversationId"] == "conv-b"
    assert payload["data"]["records"][0]["messageCount"] is None


def test_delete_session_cleans_associated_rows_transactionally() -> None:
    app, database = _build_app()
    _seed(database)

    with TestClient(app) as client:
        response = client.delete("/session/conv-a")
        detail = client.get("/session/conv-a")

    assert response.json() == {"code": 200, "message": "会话删除成功", "data": None}
    assert detail.json()["code"] == 500

    with database.session_factory() as session:
        assert session.query(AiSession).filter_by(session_id="conv-a").count() == 0
        assert session.query(AiFileInfo).filter_by(conversation_id="conv-a").count() == 0
        assert session.query(AiPptInst).filter_by(conversation_id="conv-a").count() == 0
