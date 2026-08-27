import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .agents.deep_research import DeepResearchAgent
from .agents.file import FileAgent
from .agents.ppt import PptBuilderAgent
from .agents.skills import SkillsAgent
from .agents.web_search import WebSearchAgent
from .auth import AuthenticationManager, AuthenticationMiddleware
from .config import Settings, get_settings
from .files.parser import FileParser
from .files.rag import FileRagService, build_file_rag_service
from .files.service import FileService
from .files.storage import MinioObjectStore, ObjectStoreUnavailableError
from .memory import InMemoryConversationStore
from .metrics import MetricsRegistry
from .observability import RequestContextMiddleware
from .persistence.conversation_store import SqlConversationStore
from .persistence.database import Database
from .persistence.ppt_repository import PptRepository
from .ppt.providers import PythonPptRenderer, QwenPptImageGenerator
from .providers.llm import OpenAICompatibleClient
from .providers.multimodal import OpenAICompatibleImageDescriber
from .rate_limit import RateLimitMiddleware, build_rate_limiter
from .routers.file import build_file_router
from .routers.session import build_session_router
from .schemas import AgentEvent, StopResponse
from .sse import as_sse
from .tasks import TaskManagerUnavailableError, build_task_manager
from .tools.file_content import FileContentTool
from .tools.web_search import WebSearchTool
from .tracing import TracingManager, trace_agent_stream


def create_app(settings_override: Settings | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    metrics = MetricsRegistry()
    tracing = TracingManager(settings)
    tasks = build_task_manager(settings)
    rate_limiter = build_rate_limiter(settings)
    authentication = AuthenticationManager(settings)
    database = (
        Database(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout_seconds=settings.database_pool_timeout_seconds,
            pool_recycle_seconds=settings.database_pool_recycle_seconds,
        )
        if settings.persistence_mode == "database"
        else None
    )
    memory = (
        SqlConversationStore(database.session_factory)
        if database is not None
        else InMemoryConversationStore()
    )
    provider_http_limits = httpx.Limits(
        max_connections=settings.provider_http_max_connections,
        max_keepalive_connections=settings.provider_http_max_keepalive_connections,
        keepalive_expiry=settings.provider_http_keepalive_expiry_seconds,
    )
    provider_http_client = httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        limits=provider_http_limits,
    )
    provider_sync_http_client = httpx.Client(
        timeout=settings.request_timeout_seconds,
        limits=provider_http_limits,
    )
    llm_client = OpenAICompatibleClient(settings, client=provider_http_client)
    web_search_tool = WebSearchTool(settings, client=provider_http_client)
    web_search_agent = WebSearchAgent(
        settings,
        memory,
        llm_client=llm_client,
        search_tool=web_search_tool,
    )
    deep_research_agent = DeepResearchAgent(
        settings,
        memory,
        llm_client=llm_client,
        search_tool=web_search_tool,
    )
    file_service: FileService | None = None
    file_rag_service: FileRagService | None = None
    file_content_tool: FileContentTool | None = None
    file_agent: FileAgent | None = None
    ppt_agent: PptBuilderAgent | None = None
    object_store: MinioObjectStore | None = None
    if database is not None:
        file_rag_service = build_file_rag_service(
            settings,
            llm_client=llm_client,
            provider_async_http_client=provider_http_client,
            provider_http_client=provider_sync_http_client,
        )
        object_store = (
            MinioObjectStore(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                bucket=settings.minio_bucket,
                secure=settings.minio_secure,
                public_read=settings.minio_public_read,
                connect_timeout_seconds=settings.minio_connect_timeout_seconds,
                read_timeout_seconds=settings.minio_read_timeout_seconds,
                max_retries=settings.minio_max_retries,
            )
            if settings.minio_endpoint
            else None
        )
        file_service = FileService(
            settings,
            database.session_factory,
            object_store=object_store,
            parser=FileParser(max_text_chars=settings.max_extracted_text_chars),
            image_describer=OpenAICompatibleImageDescriber(settings, client=provider_sync_http_client),
            vector_indexer=file_rag_service,
        )
        file_content_tool = FileContentTool(file_service, file_rag_service)
        file_agent = FileAgent(settings, memory, file_content_tool, llm_client=llm_client)
        ppt_repository = PptRepository(database.session_factory)
        ppt_agent = PptBuilderAgent(
            settings,
            memory,
            ppt_repository,
            PythonPptRenderer(settings, object_store),
            QwenPptImageGenerator(settings, client=provider_http_client),
            object_store,
            llm_client=llm_client,
            search_tool=web_search_tool,
            provider_http_client=provider_http_client,
        )

    skills_agent = SkillsAgent(
        settings,
        memory,
        file_content_tool,
        llm_client=llm_client,
        search_tool=web_search_tool,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await tasks.start()
        try:
            await rate_limiter.start()
            yield
        finally:
            await rate_limiter.close()
            await tasks.close()
            await provider_http_client.aclose()
            provider_sync_http_client.close()
            if file_rag_service is not None:
                file_rag_service.dispose()
            if database is not None:
                database.dispose()
            tracing.shutdown()

    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.metrics = metrics
    app.state.tracing = tracing
    app.state.memory = memory
    app.state.tasks = tasks
    app.state.rate_limiter = rate_limiter
    app.state.authentication = authentication
    app.state.provider_http_client = provider_http_client
    app.state.provider_sync_http_client = provider_sync_http_client
    app.state.llm_client = llm_client
    app.state.web_search_tool = web_search_tool
    app.state.web_search_agent = web_search_agent
    app.state.deep_research_agent = deep_research_agent
    app.state.database = database
    app.state.file_service = file_service
    app.state.file_rag_service = file_rag_service
    app.state.object_store = object_store
    app.state.file_agent = file_agent
    app.state.ppt_agent = ppt_agent
    app.state.skills_agent = skills_agent

    app.add_middleware(
        RateLimitMiddleware,
        limiter=rate_limiter,
        path_prefixes=settings.rate_limit_path_prefix_list,
        limit=settings.rate_limit_requests,
    )
    app.add_middleware(AuthenticationMiddleware, manager=authentication)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Cache-Control", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-Trace-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
        ],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, metrics=metrics, tracing=tracing)

    def database_session() -> Iterator[Session]:
        if database is None:
            raise HTTPException(
                status_code=503,
                detail="会话持久化未启用，请设置 PERSISTENCE_MODE=database",
            )
        yield from database.sessions()

    def get_file_service() -> FileService:
        if file_service is None:
            raise HTTPException(
                status_code=503,
                detail="文件持久化未启用，请设置 PERSISTENCE_MODE=database",
            )
        return file_service

    async def register_task(conversation_id: str) -> AgentEvent | None:
        try:
            acquired = await tasks.register_current(conversation_id)
        except TaskManagerUnavailableError as exc:
            return AgentEvent.error(
                "任务协调服务不可用，请稍后重试",
                code="TASK_MANAGER_UNAVAILABLE",
                detail=str(exc),
            )
        if acquired:
            return None
        return AgentEvent.error("该会话正在执行中，请稍后再试", code="TASK_ALREADY_RUNNING")

    def agent_failure_event(exc: Exception) -> AgentEvent:
        if isinstance(exc, SQLAlchemyError):
            return AgentEvent.error(
                "持久化数据库暂时不可用，请稍后重试",
                code="PERSISTENCE_UNAVAILABLE",
                detail=type(exc).__name__,
            )
        if isinstance(exc, ObjectStoreUnavailableError):
            return AgentEvent.error(
                "对象存储暂时不可用，请稍后重试",
                code="OBJECT_STORAGE_UNAVAILABLE",
                detail=type(exc).__name__,
            )
        return AgentEvent.error("Agent 执行失败", code="AGENT_EXECUTION_ERROR", detail=str(exc))

    app.include_router(build_session_router(database_session))
    app.include_router(build_file_router(get_file_service))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "persistence": settings.persistence_mode,
        }

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "alive", "service": settings.app_name}

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        checks: dict[str, dict[str, str]] = {}
        ready = True
        degraded = False

        try:
            await tasks.check_ready()
            checks["task_manager"] = {"status": "ok", "mode": settings.task_manager_mode}
        except Exception as exc:
            ready = False
            checks["task_manager"] = {"status": "error", "error": type(exc).__name__}

        try:
            await rate_limiter.check_ready()
            checks["rate_limit"] = {"status": "ok", "mode": settings.rate_limit_mode}
        except Exception as exc:
            ready = False
            checks["rate_limit"] = {"status": "error", "error": type(exc).__name__}

        if database is None:
            checks["database"] = {"status": "disabled", "mode": settings.persistence_mode}
        else:
            try:
                await asyncio.to_thread(database.ping)
                checks["database"] = {"status": "ok", "mode": settings.persistence_mode}
            except Exception as exc:
                ready = False
                checks["database"] = {"status": "error", "error": type(exc).__name__}

        if object_store is None:
            checks["minio"] = {"status": "disabled"}
        else:
            try:
                await asyncio.to_thread(object_store.check_ready)
                checks["minio"] = {"status": "ok"}
            except Exception as exc:
                degraded = True
                checks["minio"] = {"status": "degraded", "error": type(exc).__name__}

        if file_rag_service is None:
            checks["pgvector"] = {"status": "disabled"}
        else:
            try:
                await asyncio.to_thread(file_rag_service.check_ready)
                checks["pgvector"] = {"status": "ok"}
            except Exception as exc:
                degraded = True
                checks["pgvector"] = {"status": "degraded", "error": type(exc).__name__}

        if not ready:
            status = "not_ready"
        elif degraded:
            status = "degraded"
        else:
            status = "ready"
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": status, "checks": checks},
        )

    @app.get("/agent/chat/stream")
    async def chat_stream(
        query: str = Query(min_length=1),
        conversation_id: str = Query(alias="conversationId", min_length=1),
    ) -> StreamingResponse:
        async def events() -> AsyncIterator[AgentEvent]:
            registration_error = await register_task(conversation_id)
            if registration_error is not None:
                yield registration_error
                yield AgentEvent.complete()
                return

            completed = False
            try:
                async for event in web_search_agent.run(conversation_id, query):
                    completed = completed or event.type == "complete"
                    yield event
            except asyncio.CancelledError:
                yield AgentEvent(type="text", content="⏹ 用户已停止生成\n")
            except Exception as exc:
                yield agent_failure_event(exc)
            finally:
                await tasks.remove(conversation_id)

            if not completed:
                yield AgentEvent.complete()

        return StreamingResponse(
            as_sse(trace_agent_stream("websearch", events())),
            media_type="text/event-stream; charset=utf-8",
        )

    @app.get("/agent/deep/stream")
    async def deep_stream(
        query: str = Query(min_length=1),
        conversation_id: str = Query(alias="conversationId", min_length=1),
    ) -> StreamingResponse:
        async def events() -> AsyncIterator[AgentEvent]:
            registration_error = await register_task(conversation_id)
            if registration_error is not None:
                yield registration_error
                yield AgentEvent.complete()
                return

            completed = False
            try:
                async for event in deep_research_agent.run(conversation_id, query):
                    completed = completed or event.type == "complete"
                    yield event
            except asyncio.CancelledError:
                yield AgentEvent(type="text", content="⏹ 用户已停止生成\n")
            except Exception as exc:
                yield agent_failure_event(exc)
            finally:
                await tasks.remove(conversation_id)

            if not completed:
                yield AgentEvent.complete()

        return StreamingResponse(
            as_sse(trace_agent_stream("plan-execute", events())),
            media_type="text/event-stream; charset=utf-8",
        )

    @app.get("/agent/pptx/stream")
    async def pptx_stream(
        query: str = Query(min_length=1),
        conversation_id: str = Query(alias="conversationId", min_length=1),
    ) -> StreamingResponse:
        async def events() -> AsyncIterator[AgentEvent]:
            if ppt_agent is None:
                yield AgentEvent.error(
                    "PPT服务未启用，请设置 PERSISTENCE_MODE=database",
                    code="PPT_SERVICE_UNAVAILABLE",
                )
                yield AgentEvent.complete()
                return

            registration_error = await register_task(conversation_id)
            if registration_error is not None:
                yield registration_error
                yield AgentEvent.complete()
                return

            completed = False
            try:
                async for event in ppt_agent.run(conversation_id, query):
                    completed = completed or event.type == "complete"
                    yield event
            except asyncio.CancelledError:
                yield AgentEvent(type="text", content="⏹ 用户已停止生成\n")
            except Exception as exc:
                yield agent_failure_event(exc)
            finally:
                await tasks.remove(conversation_id)

            if not completed:
                yield AgentEvent.complete()

        return StreamingResponse(
            as_sse(trace_agent_stream("pptx", events())),
            media_type="text/event-stream; charset=utf-8",
        )

    @app.get("/agent/file/stream")
    async def file_stream(
        query: str = Query(min_length=1),
        conversation_id: str = Query(alias="conversationId", min_length=1),
        file_id: str = Query(alias="fileId", min_length=1),
    ) -> StreamingResponse:
        async def events() -> AsyncIterator[AgentEvent]:
            if file_agent is None:
                yield AgentEvent.error(
                    "文件问答服务未启用，请设置 PERSISTENCE_MODE=database",
                    code="FILE_SERVICE_UNAVAILABLE",
                )
                yield AgentEvent.complete()
                return

            registration_error = await register_task(conversation_id)
            if registration_error is not None:
                yield registration_error
                yield AgentEvent.complete()
                return

            completed = False
            try:
                async for event in file_agent.run(conversation_id, query, file_id):
                    completed = completed or event.type == "complete"
                    yield event
            except asyncio.CancelledError:
                yield AgentEvent(type="text", content="⏹ 用户已停止生成\n")
            except Exception as exc:
                yield agent_failure_event(exc)
            finally:
                await tasks.remove(conversation_id)

            if not completed:
                yield AgentEvent.complete()

        return StreamingResponse(
            as_sse(trace_agent_stream("file", events())),
            media_type="text/event-stream; charset=utf-8",
        )

    @app.get("/agent/skills/stream")
    async def skills_stream(
        query: str = Query(min_length=1),
        conversation_id: str = Query(alias="conversationId", min_length=1),
        file_id: str | None = Query(default=None, alias="fileId"),
    ) -> StreamingResponse:
        async def events() -> AsyncIterator[AgentEvent]:
            registration_error = await register_task(conversation_id)
            if registration_error is not None:
                yield registration_error
                yield AgentEvent.complete()
                return

            completed = False
            try:
                async for event in skills_agent.run(conversation_id, query, file_id):
                    completed = completed or event.type == "complete"
                    yield event
            except asyncio.CancelledError:
                yield AgentEvent(type="text", content="⏹ 用户已停止生成\n")
            except Exception as exc:
                yield agent_failure_event(exc)
            finally:
                await tasks.remove(conversation_id)

            if not completed:
                yield AgentEvent.complete()

        return StreamingResponse(
            as_sse(trace_agent_stream("skills", events())),
            media_type="text/event-stream; charset=utf-8",
        )

    @app.get("/agent/stop", response_model=StopResponse)
    async def stop_agent(conversation_id: str = Query(alias="conversationId", min_length=1)) -> StopResponse:
        try:
            success = await tasks.stop(conversation_id)
        except TaskManagerUnavailableError as exc:
            raise HTTPException(status_code=503, detail="任务协调服务不可用，请稍后重试") from exc
        return StopResponse(success=success, message="已停止执行" if success else "没有找到正在执行的任务或已停止")

    return app


app = create_app()
