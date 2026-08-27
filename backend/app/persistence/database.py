from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Database:
    """Small SQLAlchemy 2.x wrapper shared by API and Agent persistence."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout_seconds: int = 30,
        pool_recycle_seconds: int = 1800,
    ) -> None:
        is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        engine_options: dict[str, object] = {
            "echo": echo,
            "pool_pre_ping": not is_sqlite,
            "connect_args": connect_args,
        }
        if url in {"sqlite://", "sqlite:///:memory:"}:
            # Tests and local contract fixtures may cross FastAPI worker threads;
            # StaticPool keeps one in-memory SQLite database visible to all of them.
            engine_options["poolclass"] = StaticPool
        elif not is_sqlite:
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout_seconds,
                pool_recycle=pool_recycle_seconds,
            )
        self.engine: Engine = create_engine(url, **engine_options)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def sessions(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()
