from functools import lru_cache
from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DeepDesk"
    host: str = "127.0.0.1"
    port: int = 8888
    deployment_mode: str = "development"

    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen-plus"
    openai_temperature: float = 0.7

    # Optional provider overrides. Leave empty to inherit OPENAI_*.
    query_rewrite_api_key: str = ""
    query_rewrite_base_url: str = ""
    query_rewrite_model: str = ""
    vision_api_key: str = ""
    vision_base_url: str = ""
    vision_model: str = ""

    search_mode: str = "demo"
    tavily_api_key: str = ""
    tavily_endpoint: str = "https://api.tavily.com/search"

    # Keep local demo runnable without infrastructure. Set to "database" when
    # durable MySQL-backed sessions are required.
    persistence_mode: str = "memory"
    database_url: str = ""
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800

    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "rag-test2"
    minio_secure: bool = False
    minio_public_read: bool = True
    minio_connect_timeout_seconds: int = 5
    minio_read_timeout_seconds: int = 30
    minio_max_retries: int = 2

    max_file_size_bytes: int = 50 * 1024 * 1024
    large_file_threshold_chars: int = 5000
    max_extracted_text_chars: int = 20000
    file_chunk_size_chars: int = 500
    file_chunk_overlap_chars: int = 50
    image_model: str = "qwen3-vl-plus"

    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-v4"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 9
    vector_database_url: str = ""
    vector_table_name: str = "vector_file_info"
    vector_connect_timeout_seconds: int = 5
    rag_top_k: int = 5
    rag_multi_query_count: int = 3

    # Phase 3 Skills Agent. Local tools are sandboxed under skills_workspace_root.
    skills_workspace_root: str = "./agent-workspace"
    skills_directories: str = "./skills"
    skills_max_file_size_bytes: int = 10 * 1024 * 1024
    skills_read_line_limit: int = 500
    skills_grep_head_limit: int = 250
    skills_bash_enabled: bool = False
    skills_bash_timeout_seconds: int = 30
    skills_bash_max_output_bytes: int = 100_000
    skills_bash_allowed_commands: str = "git"
    skills_max_agent_rounds: int = 10
    skills_max_retries: int = 3
    skills_retry_interval_seconds: float = 10.0
    skills_context_token_threshold: int = 60_000
    skills_context_keep_recent_tools: int = 4
    skills_context_max_tool_length: int = 200

    # Plan-Execute Deep Research settings.
    deep_max_rounds: int = 3
    deep_context_char_limit: int = 50_000
    deep_tool_concurrency: int = 3
    deep_tool_retries: int = 2
    deep_task_agent_rounds: int = 5

    # Phase 5 PPT Builder. Keep the existing render_ppt.py as the rendering engine.
    ppt_render_script_path: str = "./resources/python/render_ppt.py"
    ppt_output_dir: str = "./output/ppt"
    ppt_render_timeout_seconds: int = 300
    ppt_schema_env_threshold_chars: int = 20_000
    ppt_image_model: str = "qwen-image-plus"
    ppt_image_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    ppt_image_timeout_seconds: int = 300
    ppt_image_download_timeout_seconds: int = 30

    # Phase 6 distributed task manager. local keeps dev/tests infrastructure-free.
    task_manager_mode: str = "local"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_connect_timeout_seconds: int = 5
    redis_socket_timeout_seconds: int = 5
    task_ttl_seconds: int = 30 * 60
    task_ttl_refresh_seconds: int = 5 * 60
    task_stop_topic: str = "agent:stop"
    task_key_prefix: str = "agent:task:"

    max_agent_rounds: int = 5
    request_timeout_seconds: float = 120.0
    provider_max_retries: int = 2
    provider_retry_base_seconds: float = 0.5
    provider_retry_max_seconds: float = 5.0
    provider_http_max_connections: int = 100
    provider_http_max_keepalive_connections: int = 20
    provider_http_keepalive_expiry_seconds: float = 30.0
    enable_recommendations: bool = True

    tracing_enabled: bool = False
    tracing_exporter: str = "none"
    tracing_otlp_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    tracing_sample_ratio: float = 1.0

    rate_limit_mode: str = "off"
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    rate_limit_path_prefixes: str = (
        "/agent/chat/stream,/agent/file/stream,/agent/skills/stream,"
        "/agent/deep/stream,/agent/pptx/stream,/file/upload"
    )
    rate_limit_key_prefix: str = "rate_limit:"

    auth_mode: str = "off"
    auth_api_keys_json: SecretStr = SecretStr("{}")
    auth_public_paths: str = "/health,/health/live,/health/ready"

    # Development frontends are commonly served from :8080 while this service
    # listens on :8888, so cross-origin access is enabled for those origins.
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"

    @field_validator("deployment_mode")
    @classmethod
    def validate_deployment_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "production"}:
            raise ValueError("DEPLOYMENT_MODE 仅支持 development 或 production")
        return normalized

    @field_validator("search_mode")
    @classmethod
    def validate_search_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"demo", "tavily"}:
            raise ValueError("SEARCH_MODE 仅支持 demo 或 tavily")
        return normalized

    @field_validator("persistence_mode")
    @classmethod
    def validate_persistence_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"memory", "database"}:
            raise ValueError("PERSISTENCE_MODE 仅支持 memory 或 database")
        return normalized

    @field_validator("task_manager_mode")
    @classmethod
    def validate_task_manager_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "redis"}:
            raise ValueError("TASK_MANAGER_MODE 仅支持 local 或 redis")
        return normalized

    @field_validator("tracing_exporter")
    @classmethod
    def validate_tracing_exporter(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"none", "console", "otlp"}:
            raise ValueError("TRACING_EXPORTER 仅支持 none、console 或 otlp")
        return normalized

    @field_validator("rate_limit_mode")
    @classmethod
    def validate_rate_limit_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"off", "local", "redis"}:
            raise ValueError("RATE_LIMIT_MODE 仅支持 off、local 或 redis")
        return normalized

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"off", "api_key"}:
            raise ValueError("AUTH_MODE 仅支持 off 或 api_key")
        return normalized

    @field_validator("tracing_sample_ratio")
    @classmethod
    def validate_tracing_sample_ratio(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("TRACING_SAMPLE_RATIO 必须位于 0 到 1 之间")
        return value

    @field_validator("deep_max_rounds", "deep_context_char_limit", "deep_tool_concurrency", "deep_task_agent_rounds")
    @classmethod
    def validate_positive_deep_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Deep Research 正整数配置必须 >= 1")
        return value

    @field_validator("deep_tool_retries")
    @classmethod
    def validate_deep_tool_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("DEEP_TOOL_RETRIES 必须 >= 0")
        return value

    @field_validator("provider_max_retries")
    @classmethod
    def validate_provider_max_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("PROVIDER_MAX_RETRIES 必须 >= 0")
        return value

    @field_validator("request_timeout_seconds", "provider_http_keepalive_expiry_seconds")
    @classmethod
    def validate_positive_http_float_settings(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("HTTP timeout/keepalive 配置必须 > 0")
        return value

    @field_validator("provider_http_max_connections", "provider_http_max_keepalive_connections")
    @classmethod
    def validate_positive_http_pool_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("HTTP connection pool 配置必须 >= 1")
        return value

    @field_validator("rate_limit_requests", "rate_limit_window_seconds")
    @classmethod
    def validate_positive_rate_limit_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Rate limit 正整数配置必须 >= 1")
        return value

    @field_validator("rate_limit_path_prefixes")
    @classmethod
    def validate_rate_limit_paths(cls, value: str) -> str:
        prefixes = [prefix.strip() for prefix in value.split(",") if prefix.strip()]
        if not prefixes or any(not prefix.startswith("/") for prefix in prefixes):
            raise ValueError("RATE_LIMIT_PATH_PREFIXES 必须是以 / 开头的非空路径列表")
        return ",".join(prefixes)

    @field_validator("rate_limit_key_prefix")
    @classmethod
    def validate_rate_limit_key_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("RATE_LIMIT_KEY_PREFIX 不能为空")
        return normalized

    @field_validator("auth_public_paths")
    @classmethod
    def validate_auth_public_paths(cls, value: str) -> str:
        paths = [path.strip() for path in value.split(",") if path.strip()]
        if any(not path.startswith("/") for path in paths):
            raise ValueError("AUTH_PUBLIC_PATHS 必须使用以 / 开头的路径")
        return ",".join(paths)

    @field_validator("database_pool_size", "database_pool_timeout_seconds", "database_pool_recycle_seconds")
    @classmethod
    def validate_positive_database_pool_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Database pool 正整数配置必须 >= 1")
        return value

    @field_validator("database_max_overflow")
    @classmethod
    def validate_database_max_overflow(cls, value: int) -> int:
        if value < 0:
            raise ValueError("DATABASE_MAX_OVERFLOW 必须 >= 0")
        return value

    @field_validator("provider_retry_base_seconds", "provider_retry_max_seconds")
    @classmethod
    def validate_non_negative_provider_retry_delay(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Provider retry delay 必须 >= 0")
        return value

    @field_validator(
        "ppt_render_timeout_seconds",
        "ppt_schema_env_threshold_chars",
        "ppt_image_timeout_seconds",
        "ppt_image_download_timeout_seconds",
    )
    @classmethod
    def validate_positive_ppt_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("PPT 正整数配置必须 >= 1")
        return value

    @field_validator(
        "redis_socket_connect_timeout_seconds",
        "redis_socket_timeout_seconds",
        "task_ttl_seconds",
        "task_ttl_refresh_seconds",
    )
    @classmethod
    def validate_positive_task_settings(cls, value: int) -> int:
        if value < 1:
            raise ValueError("TaskManager 正整数配置必须 >= 1")
        return value

    @model_validator(mode="after")
    def validate_cross_field_settings(self) -> Self:
        if self.task_manager_mode == "redis" and self.task_ttl_refresh_seconds >= self.task_ttl_seconds:
            raise ValueError("TASK_TTL_REFRESH_SECONDS 必须小于 TASK_TTL_SECONDS")
        if self.provider_retry_max_seconds < self.provider_retry_base_seconds:
            raise ValueError("PROVIDER_RETRY_MAX_SECONDS 必须 >= PROVIDER_RETRY_BASE_SECONDS")
        if self.provider_http_max_keepalive_connections > self.provider_http_max_connections:
            raise ValueError("PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS 必须 <= PROVIDER_HTTP_MAX_CONNECTIONS")
        if self.tracing_enabled and self.tracing_exporter == "otlp" and not self.tracing_otlp_endpoint.strip():
            raise ValueError("TRACING_EXPORTER=otlp 时必须配置 TRACING_OTLP_ENDPOINT")
        if self.persistence_mode == "database" and not self.database_url.strip():
            raise ValueError("PERSISTENCE_MODE=database 时必须配置 DATABASE_URL")
        if self.deployment_mode == "production":
            self._validate_production_settings()
        return self

    def _validate_production_settings(self) -> None:
        origins = self.cors_origin_list
        if not origins:
            raise ValueError("production 必须配置 CORS_ORIGINS 正式域名白名单")
        if any(
            origin == "*"
            or "localhost" in origin.lower()
            or "127.0.0.1" in origin
            or not origin.lower().startswith("https://")
            for origin in origins
        ):
            raise ValueError("production CORS_ORIGINS 只允许显式 HTTPS 非本地域名")
        if self.auth_mode == "off":
            raise ValueError("production 必须启用 AUTH_MODE")
        if self.rate_limit_mode == "off":
            raise ValueError("production 必须启用 RATE_LIMIT_MODE")
        if self.task_manager_mode == "redis" and self.rate_limit_mode != "redis":
            raise ValueError("多实例 production 使用 Redis TaskManager 时 RATE_LIMIT_MODE 也必须为 redis")
        if _looks_placeholder_secret(self.openai_api_key):
            raise ValueError("production 必须通过环境变量配置有效 OPENAI_API_KEY")
        if self.vector_database_url.strip() and _looks_placeholder_secret(self.embedding_provider_api_key):
            raise ValueError("production 启用 VECTOR_DATABASE_URL 时必须配置有效 EMBEDDING_API_KEY/OPENAI_API_KEY")
        if self.search_mode == "tavily" and _looks_placeholder_secret(self.tavily_api_key):
            raise ValueError("SEARCH_MODE=tavily 时必须配置有效 TAVILY_API_KEY")
        if self.minio_endpoint and (
            _looks_placeholder_secret(self.minio_access_key)
            or _looks_placeholder_secret(self.minio_secret_key)
            or self.minio_access_key.lower() == "minioadmin"
            or self.minio_secret_key.lower() == "minioadmin"
        ):
            raise ValueError("production MinIO 禁止使用空值、占位值或 minioadmin 默认凭据")
        if self.database_echo:
            raise ValueError("production 必须关闭 DATABASE_ECHO，避免 SQL/参数泄露到日志")
        if "//root:root@" in self.database_url.lower():
            raise ValueError("production DATABASE_URL 禁止使用 root/root 弱凭据")

    @property
    def embedding_provider_api_key(self) -> str:
        return self.embedding_api_key.strip() or self.openai_api_key.strip()

    @property
    def embedding_provider_base_url(self) -> str:
        return self.embedding_base_url.strip() or self.openai_base_url.strip()

    @property
    def query_rewrite_provider_api_key(self) -> str:
        return self.query_rewrite_api_key.strip() or self.openai_api_key.strip()

    @property
    def query_rewrite_provider_base_url(self) -> str:
        return self.query_rewrite_base_url.strip() or self.openai_base_url.strip()

    @property
    def query_rewrite_provider_model(self) -> str:
        return self.query_rewrite_model.strip() or self.openai_model.strip()

    @property
    def vision_provider_api_key(self) -> str:
        return self.vision_api_key.strip() or self.openai_api_key.strip()

    @property
    def vision_provider_base_url(self) -> str:
        return self.vision_base_url.strip() or self.openai_base_url.strip()

    @property
    def vision_provider_model(self) -> str:
        return self.vision_model.strip() or self.image_model.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def skills_directory_list(self) -> list[str]:
        return [path.strip() for path in self.skills_directories.split(",") if path.strip()]

    @property
    def skills_bash_allowed_command_list(self) -> list[str]:
        return [command.strip() for command in self.skills_bash_allowed_commands.split(",") if command.strip()]

    @property
    def rate_limit_path_prefix_list(self) -> tuple[str, ...]:
        return tuple(
            prefix.strip()
            for prefix in self.rate_limit_path_prefixes.split(",")
            if prefix.strip().startswith("/")
        )

    @property
    def auth_public_path_list(self) -> tuple[str, ...]:
        return tuple(path.strip() for path in self.auth_public_paths.split(",") if path.strip())


def _looks_placeholder_secret(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized in {"replace-me", "change-me", "your-key", "your-api-key", "test", "test-key"}
        or normalized.startswith("your-")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

