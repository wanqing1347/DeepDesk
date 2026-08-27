import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.schemas import AgentEvent

_AGENT_TOKEN = "agent-token-12345678901234567890"
_OTHER_AGENT_TOKEN = "other-agent-token-123456789012345"
_OPS_TOKEN = "ops-token-1234567890123456789012"


def _auth_settings(**overrides) -> Settings:
    defaults = {
        "auth_mode": "api_key",
        "auth_api_keys_json": json.dumps(
            {
                "frontend": {"token": _AGENT_TOKEN, "scopes": ["agent", "file", "session"]},
                "other": {"token": _OTHER_AGENT_TOKEN, "scopes": ["agent"]},
                "ops": {"token": _OPS_TOKEN, "scopes": ["*"]},
            }
        ),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_is_optional_but_protects_non_health_routes_when_enabled() -> None:
    app = create_app(_auth_settings())

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run
    with TestClient(app) as client:
        health = client.get("/health/live")
        missing = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "auth-missing"},
            headers={"Origin": "http://localhost:8080"},
        )
        invalid = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "auth-invalid"},
            headers=_bearer("invalid-token-that-is-long-enough"),
        )
        allowed = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "auth-ok"},
            headers=_bearer(_AGENT_TOKEN),
        )

    assert health.status_code == 200
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert invalid.status_code == 401
    assert allowed.status_code == 200
    assert '"type": "complete"' in allowed.text


def test_authorization_scopes_protect_metrics_and_admin_routes() -> None:
    app = create_app(_auth_settings())
    with TestClient(app) as client:
        forbidden_metrics = client.get("/metrics", headers=_bearer(_AGENT_TOKEN))
        allowed_metrics = client.get("/metrics", headers=_bearer(_OPS_TOKEN))
        forbidden_docs = client.get("/openapi.json", headers=_bearer(_AGENT_TOKEN))
        allowed_docs = client.get("/openapi.json", headers=_bearer(_OPS_TOKEN))

    assert forbidden_metrics.status_code == 403
    assert allowed_metrics.status_code == 200
    assert forbidden_docs.status_code == 403
    assert allowed_docs.status_code == 200


def test_authenticated_principal_is_used_as_rate_limit_identity() -> None:
    app = create_app(
        _auth_settings(
            rate_limit_mode="local",
            rate_limit_requests=1,
            rate_limit_window_seconds=60,
        )
    )

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run
    with TestClient(app) as client:
        first = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "principal-a1"},
            headers=_bearer(_AGENT_TOKEN),
        )
        blocked = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "principal-a2"},
            headers=_bearer(_AGENT_TOKEN),
        )
        other_principal = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "principal-b1"},
            headers=_bearer(_OTHER_AGENT_TOKEN),
        )

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert other_principal.status_code == 200


def test_auth_failure_metrics_do_not_include_token_or_principal() -> None:
    app = create_app(_auth_settings())
    with TestClient(app) as client:
        client.get("/metrics")
        client.get("/metrics", headers=_bearer("invalid-token-that-is-long-enough"))
        metrics = client.get("/metrics", headers=_bearer(_OPS_TOKEN)).text

    assert 'deepdesk_auth_failures_total{reason="missing"} 1' in metrics
    assert 'deepdesk_auth_failures_total{reason="invalid"} 1' in metrics
    assert _AGENT_TOKEN not in metrics
    assert _OPS_TOKEN not in metrics
    assert "frontend" not in metrics


def test_cors_preflight_does_not_require_authentication() -> None:
    app = create_app(_auth_settings())
    with TestClient(app) as client:
        response = client.options(
            "/agent/chat/stream",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"


def test_auth_configuration_rejects_weak_tokens_and_unknown_scopes() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_mode="unknown")
    with pytest.raises(ValueError):
        create_app(
            Settings(
                auth_mode="api_key",
                auth_api_keys_json=json.dumps({"frontend": {"token": "short", "scopes": ["agent"]}}),
            )
        )
    with pytest.raises(ValueError):
        create_app(
            Settings(
                auth_mode="api_key",
                auth_api_keys_json=json.dumps(
                    {"frontend": {"token": _AGENT_TOKEN, "scopes": ["unknown-scope"]}}
                ),
            )
        )


def test_auth_manager_keeps_only_token_digests_after_startup() -> None:
    app = create_app(_auth_settings())
    credentials_repr = repr(app.state.authentication._credentials)

    assert _AGENT_TOKEN not in credentials_repr
    assert _OPS_TOKEN not in credentials_repr
    assert app.state.authentication.authenticate(_AGENT_TOKEN).name == "frontend"
