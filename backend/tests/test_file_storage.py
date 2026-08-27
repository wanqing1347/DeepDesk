from typing import Any

import pytest

import app.files.storage as storage_module
from app.files.storage import MinioObjectStore


def test_minio_client_uses_bounded_network_timeouts_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeMinio:
        def __init__(self, endpoint: str, **kwargs: Any) -> None:
            captured["endpoint"] = endpoint
            captured.update(kwargs)

    monkeypatch.setattr(storage_module, "Minio", FakeMinio)

    MinioObjectStore(
        endpoint="http://127.0.0.1:9000/",
        access_key="access",
        secret_key="secret",
        bucket="bucket",
        secure=False,
        public_read=True,
        connect_timeout_seconds=3,
        read_timeout_seconds=7,
        max_retries=1,
    )

    assert captured["endpoint"] == "127.0.0.1:9000"
    http_client = captured["http_client"]
    timeout = http_client.connection_pool_kw["timeout"]
    retries = http_client.connection_pool_kw["retries"]
    assert timeout.connect_timeout == 3
    assert timeout.read_timeout == 7
    assert retries.total == 1


def test_minio_timeout_values_are_clamped_to_safe_minimums(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeMinio:
        def __init__(self, endpoint: str, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(storage_module, "Minio", FakeMinio)

    MinioObjectStore(
        endpoint="127.0.0.1:9000",
        access_key="access",
        secret_key="secret",
        bucket="bucket",
        secure=False,
        public_read=False,
        connect_timeout_seconds=0,
        read_timeout_seconds=0,
        max_retries=-1,
    )

    http_client = captured["http_client"]
    timeout = http_client.connection_pool_kw["timeout"]
    retries = http_client.connection_pool_kw["retries"]
    assert timeout.connect_timeout == 1
    assert timeout.read_timeout == 1
    assert retries.total == 0
