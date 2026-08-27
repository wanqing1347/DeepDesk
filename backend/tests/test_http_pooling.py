import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


def test_create_app_shares_provider_http_client_and_closes_it_on_shutdown() -> None:
    app = create_app(
        Settings(
            persistence_mode="database",
            database_url="sqlite://",
            vector_database_url="postgresql+psycopg://postgres:postgres@127.0.0.1:65432/test",
        )
    )
    shared_client = app.state.provider_http_client
    shared_sync_client = app.state.provider_sync_http_client

    assert app.state.llm_client._client is shared_client
    assert app.state.web_search_tool._client is shared_client
    assert app.state.web_search_agent._llm is app.state.llm_client
    assert app.state.web_search_agent._search is app.state.web_search_tool
    assert app.state.deep_research_agent._llm is app.state.llm_client
    assert app.state.deep_research_agent._search is app.state.web_search_tool
    assert app.state.skills_agent._llm is app.state.llm_client
    assert app.state.skills_agent._search is app.state.web_search_tool
    assert app.state.file_agent is not None
    assert app.state.file_agent._llm is app.state.llm_client
    assert app.state.file_service is not None
    assert app.state.file_service._image_describer._client is shared_sync_client
    assert app.state.file_rag_service is not None
    assert app.state.file_rag_service._embedding_provider._client is shared_sync_client
    assert app.state.ppt_agent is not None
    assert app.state.ppt_agent._llm is app.state.llm_client
    assert app.state.ppt_agent._search is app.state.web_search_tool
    assert app.state.ppt_agent._image_generator._client is shared_client
    assert app.state.ppt_agent._provider_http_client is shared_client
    assert shared_client.is_closed is False
    assert shared_sync_client.is_closed is False

    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert shared_client.is_closed is False
        assert shared_sync_client.is_closed is False

    assert shared_client.is_closed is True
    assert shared_sync_client.is_closed is True


def test_provider_http_pool_settings_validate_connection_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(provider_http_max_connections=0)
    with pytest.raises(ValidationError):
        Settings(provider_http_max_keepalive_connections=0)
    with pytest.raises(ValidationError):
        Settings(
            provider_http_max_connections=10,
            provider_http_max_keepalive_connections=11,
        )
    with pytest.raises(ValidationError):
        Settings(provider_http_keepalive_expiry_seconds=0)
