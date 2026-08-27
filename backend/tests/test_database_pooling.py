import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.pool import StaticPool

import app.persistence.database as database_module
from app.config import Settings
from app.persistence.database import Database


def test_database_applies_explicit_pool_settings_to_non_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return sqlalchemy_create_engine("sqlite://")

    monkeypatch.setattr(database_module, "create_engine", fake_create_engine)
    database = Database(
        "mysql+pymysql://user:pass@127.0.0.1:3306/deepdesk",
        pool_size=7,
        max_overflow=11,
        pool_timeout_seconds=13,
        pool_recycle_seconds=17,
    )
    try:
        assert captured["pool_pre_ping"] is True
        assert captured["pool_size"] == 7
        assert captured["max_overflow"] == 11
        assert captured["pool_timeout"] == 13
        assert captured["pool_recycle"] == 17
    finally:
        database.dispose()


def test_database_keeps_in_memory_sqlite_static_pool_without_mysql_pool_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return sqlalchemy_create_engine("sqlite://", poolclass=StaticPool)

    monkeypatch.setattr(database_module, "create_engine", fake_create_engine)
    database = Database(
        "sqlite:///:memory:",
        pool_size=7,
        max_overflow=11,
        pool_timeout_seconds=13,
        pool_recycle_seconds=17,
    )
    try:
        assert captured["pool_pre_ping"] is False
        assert captured["poolclass"] is StaticPool
        assert "pool_size" not in captured
        assert "max_overflow" not in captured
        assert "pool_timeout" not in captured
        assert "pool_recycle" not in captured
    finally:
        database.dispose()


def test_database_pool_settings_validate_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(database_pool_size=0)
    with pytest.raises(ValidationError):
        Settings(database_max_overflow=-1)
    with pytest.raises(ValidationError):
        Settings(database_pool_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(database_pool_recycle_seconds=0)
