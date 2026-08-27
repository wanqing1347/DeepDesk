import json
import logging

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app
from app.schemas import AgentEvent
from app.tasks import TaskManagerUnavailableError


def test_liveness_and_memory_mode_readiness_are_healthy_and_have_request_ids() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready", headers={"X-Request-ID": "ready-request-id"})

    assert live.status_code == 200
    assert live.json()["status"] == "alive"
    assert len(live.headers["x-request-id"]) == 32
    assert ready.status_code == 200
    assert ready.headers["x-request-id"] == "ready-request-id"
    assert ready.json() == {
        "status": "ready",
        "checks": {
            "task_manager": {"status": "ok", "mode": "local"},
            "rate_limit": {"status": "ok", "mode": "off"},
            "database": {"status": "disabled", "mode": "memory"},
            "minio": {"status": "disabled"},
            "pgvector": {"status": "disabled"},
        },
    }


def test_database_mode_readiness_executes_real_select_one() -> None:
    app = create_app(
        Settings(
            persistence_mode="database",
            database_url="sqlite://",
        )
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == {"status": "ok", "mode": "database"}


def test_readiness_returns_503_when_database_ping_fails() -> None:
    app = create_app(
        Settings(
            persistence_mode="database",
            database_url="sqlite://",
        )
    )
    database = app.state.database
    assert database is not None

    def fail_ping() -> None:
        raise RuntimeError("database unavailable with private details")

    database.ping = fail_ping
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"] == {"status": "error", "error": "RuntimeError"}
    assert "private details" not in response.text


def test_readiness_returns_503_when_task_backend_is_not_ready() -> None:
    app = create_app(Settings())

    async def fail_ready() -> None:
        raise TaskManagerUnavailableError("redis unavailable")

    app.state.tasks.check_ready = fail_ready
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["task_manager"] == {
        "status": "error",
        "error": "TaskManagerUnavailableError",
    }


def test_readiness_stays_200_but_reports_degraded_when_minio_and_pgvector_are_down() -> None:
    app = create_app(
        Settings(
            persistence_mode="database",
            database_url="sqlite://",
            minio_endpoint="http://127.0.0.1:9000",
            minio_access_key="access",
            minio_secret_key="secret",
            vector_database_url="postgresql+psycopg://user:pass@127.0.0.1:5432/vector",
        )
    )
    assert app.state.object_store is not None
    assert app.state.file_rag_service is not None

    def fail_minio() -> None:
        raise RuntimeError("minio private endpoint detail")

    def fail_pgvector() -> None:
        raise RuntimeError("pgvector private endpoint detail")

    app.state.object_store.check_ready = fail_minio
    app.state.file_rag_service.check_ready = fail_pgvector
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["database"] == {"status": "ok", "mode": "database"}
    assert payload["checks"]["minio"] == {"status": "degraded", "error": "RuntimeError"}
    assert payload["checks"]["pgvector"] == {"status": "degraded", "error": "RuntimeError"}
    assert "private endpoint detail" not in response.text


def test_database_outage_in_agent_stream_fails_closed_with_canonical_error_and_complete() -> None:
    app = create_app(
        Settings(
            persistence_mode="database",
            database_url="sqlite://",
        )
    )

    async def fail_get(_conversation_id: str):
        raise OperationalError("SELECT ...", {}, RuntimeError("mysql private connection detail"))

    app.state.memory.get = fail_get
    with TestClient(app) as client:
        response = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "db-outage"},
        )

    assert response.status_code == 200
    assert '"code": "PERSISTENCE_UNAVAILABLE"' in response.text
    assert '"detail": "OperationalError"' in response.text
    assert '"type": "complete"' in response.text
    assert "mysql private connection detail" not in response.text


def test_stream_access_log_contains_request_conversation_agent_and_final_duration(caplog) -> None:
    app = create_app(Settings())

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run

    with caplog.at_level(logging.INFO, logger="deepdesk.access"), TestClient(app) as client:
        response = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "obs-conversation"},
            headers={"X-Request-ID": "obs-request"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "obs-request"
    access_records = [record for record in caplog.records if record.name == "deepdesk.access"]
    assert access_records
    payload = json.loads(access_records[-1].getMessage())
    assert payload["event"] == "http_request"
    assert payload["request_id"] == "obs-request"
    assert payload["conversation_id"] == "obs-conversation"
    assert payload["agent_type"] == "websearch"
    assert payload["path"] == "/agent/chat/stream"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] >= 0
