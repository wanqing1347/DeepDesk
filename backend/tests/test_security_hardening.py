import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

_PROD_TOKEN = "production-auth-token-123456789012345"


def _production_settings(**overrides) -> Settings:
    defaults = {
        "deployment_mode": "production",
        "cors_origins": "https://app.example.com",
        "auth_mode": "api_key",
        "auth_api_keys_json": json.dumps(
            {"frontend": {"token": _PROD_TOKEN, "scopes": ["agent", "file", "session", "metrics"]}}
        ),
        "rate_limit_mode": "local",
        "openai_api_key": "production-model-key-123456789012345",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_development_defaults_keep_secrets_out_of_database_url() -> None:
    settings = Settings()
    assert settings.deployment_mode == "development"
    assert settings.database_url == ""
    assert settings.auth_mode == "off"
    assert settings.rate_limit_mode == "off"


def test_production_requires_https_cors_auth_rate_limit_and_real_provider_key() -> None:
    with pytest.raises(ValidationError):
        _production_settings(cors_origins="http://localhost:8080")
    with pytest.raises(ValidationError):
        _production_settings(cors_origins="*")
    with pytest.raises(ValidationError):
        _production_settings(auth_mode="off")
    with pytest.raises(ValidationError):
        _production_settings(rate_limit_mode="off")
    with pytest.raises(ValidationError):
        _production_settings(openai_api_key="replace-me")


def test_production_rejects_placeholder_embedding_key_when_vector_rag_is_enabled() -> None:
    with pytest.raises(ValidationError):
        _production_settings(
            vector_database_url="postgresql+psycopg://vector:secret@vector.example.com:5432/vector_store",
            embedding_api_key="replace-me",
        )


def test_production_rejects_weak_database_minio_and_tavily_configuration() -> None:
    with pytest.raises(ValidationError):
        _production_settings(
            persistence_mode="database",
            database_url="mysql+pymysql://root:root@db.example.com:3306/deepdesk",
        )
    with pytest.raises(ValidationError):
        _production_settings(
            minio_endpoint="https://minio.example.com",
            minio_access_key="minioadmin",
            minio_secret_key="minioadmin",
        )
    with pytest.raises(ValidationError):
        _production_settings(search_mode="tavily", tavily_api_key="")
    with pytest.raises(ValidationError):
        _production_settings(database_echo=True)


def test_multi_instance_production_requires_distributed_rate_limit() -> None:
    with pytest.raises(ValidationError):
        _production_settings(task_manager_mode="redis", rate_limit_mode="local")


def test_database_mode_requires_explicit_database_url_even_in_development() -> None:
    with pytest.raises(ValidationError):
        Settings(persistence_mode="database", database_url="")


def test_production_cors_uses_explicit_origin_and_header_allowlists() -> None:
    app = create_app(_production_settings())
    with TestClient(app) as client:
        allowed = client.options(
            "/agent/chat/stream",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-request-id",
            },
        )
        unknown_header = client.options(
            "/agent/chat/stream",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-unapproved-secret-header",
            },
        )
        foreign_origin = client.get(
            "/health/live",
            headers={"Origin": "https://evil.example.com"},
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    assert unknown_header.status_code == 400
    assert "access-control-allow-origin" not in foreign_origin.headers


def test_valid_production_configuration_can_start_without_external_backends() -> None:
    app = create_app(_production_settings())
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
