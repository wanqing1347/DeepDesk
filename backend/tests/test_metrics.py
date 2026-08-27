import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.metrics import record_provider_retry, record_tool_call
from app.schemas import AgentEvent


def test_metrics_endpoint_tracks_agent_latency_errors_tools_and_retries() -> None:
    app = create_app(Settings())

    async def fake_run(_conversation_id: str, query: str):
        tool_started_at = time.perf_counter()
        if query == "fail":
            record_tool_call("web_search", started_at=tool_started_at, outcome="error")
            record_provider_retry("tavily", "search")
            yield AgentEvent.error("search failed", code="SEARCH_FAILED")
        else:
            record_tool_call("web_search", started_at=tool_started_at, outcome="success")
            yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run

    with TestClient(app) as client:
        success = client.get(
            "/agent/chat/stream",
            params={"query": "ok", "conversationId": "metrics-success"},
        )
        failure = client.get(
            "/agent/chat/stream",
            params={"query": "fail", "conversationId": "metrics-failure"},
        )
        metrics = client.get("/metrics")

    assert success.status_code == 200
    assert failure.status_code == 200
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    body = metrics.text

    assert 'deepdesk_agent_requests_total{agent_type="websearch",status_code="200"} 2' in body
    assert 'deepdesk_agent_first_response_seconds_count{agent_type="websearch"} 2' in body
    assert 'deepdesk_agent_request_duration_seconds_count{agent_type="websearch",status_code="200"} 2' in body
    assert 'deepdesk_agent_errors_total{agent_type="websearch",code="SEARCH_FAILED"} 1' in body
    assert (
        'deepdesk_agent_tool_calls_total{agent_type="websearch",outcome="success",tool_name="web_search"} 1' in body
    )
    assert 'deepdesk_agent_tool_calls_total{agent_type="websearch",outcome="error",tool_name="web_search"} 1' in body
    assert (
        'deepdesk_agent_tool_duration_seconds_count{agent_type="websearch",outcome="success",tool_name="web_search"} 1'
        in body
    )
    assert (
        'deepdesk_agent_provider_retries_total{agent_type="websearch",operation="search",provider="tavily"} 1' in body
    )


def test_metrics_are_isolated_per_app_instance() -> None:
    first = create_app(Settings())
    second = create_app(Settings())

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    first.state.web_search_agent.run = fake_run
    second.state.web_search_agent.run = fake_run

    with TestClient(first) as first_client:
        first_client.get(
            "/agent/chat/stream",
            params={"query": "one", "conversationId": "first"},
        )
        first_metrics = first_client.get("/metrics").text

    with TestClient(second) as second_client:
        second_metrics = second_client.get("/metrics").text

    assert 'deepdesk_agent_requests_total{agent_type="websearch",status_code="200"} 1' in first_metrics
    assert "deepdesk_agent_requests_total" not in second_metrics
