# DeepDesk Backend

`DeepDesk Backend` 是 DeepDesk monorepo 中基于 FastAPI 的多 Agent 服务，提供联网搜索、文件问答与 RAG、Skills、Deep Research、PPT 生成、会话持久化和生产可观测性能力。

## 功能

### Agent

- WebSearch：`/agent/chat/stream`
  - OpenAI-compatible 模型
  - Tavily REST 搜索或本地 demo 搜索
  - 真流式文本
  - 多 tool-call
  - `tool_start/tool_end/reference/recommend/complete` Canonical SSE
  - 最大轮次 force-final
- File Agent：`/agent/file/stream`
  - 小文件直接文本上下文
  - 大文件 PgVector RAG
  - Query Rewrite / MultiQuery
  - PDF、DOCX、TXT 与常见图片输入
- Skills Agent：`/agent/skills/stream`
  - skill discovery / `read_skill`
  - WebSearch、FileContent
  - 受限 FileSystem、Grep、Bash
  - context compaction、重试、stop
- Deep Research：`/agent/deep/stream`
  - requirement clarification
  - research topic generation
  - structured plan
  - 同 order 并发任务
  - 搜索工具循环与重试
  - critique / context compression
  - 流式最终报告与 reference
- PPT Builder：`/agent/pptx/stream`
  - CREATE / MODIFY / RESUME
  - requirement / search / outline / template / schema / render 状态机
  - `qwen-image-plus` 图片生成 adapter
  - 本地 `render_ppt.py` 渲染
  - MinIO 输出

### 文件与会话 API

文件：

- `POST /file/upload`
- `GET /file/info/{file_id}`
- `GET /file/content/{file_id}`
- `GET /file/list`
- `GET /file/exists/{file_id}`
- `DELETE /file/{file_id}`

会话：

- `GET /session/list`
- `GET /session/{conversation_id}`
- `DELETE /session/{conversation_id}`

PPT 资产：

- `GET /ppt/list`
- `GET /ppt/{ppt_id}`
- `DELETE /ppt/{ppt_id}`

任务：

- `GET /agent/stop`

### 生产能力

- SQLAlchemy 数据库连接池
- provider HTTP connection pooling
- retry / exponential backoff
- Redis 分布式 TaskManager
- Redis/local rate limit
- Bearer API key + scope authorization
- CORS 与 production secret hardening
- structured access log / request context
- Prometheus metrics
- OpenTelemetry tracing
- liveness / readiness
- graceful shutdown
- MySQL、Redis、PgVector、MinIO 故障降级策略

## 环境要求

- Python 3.11+
- 可选 MySQL
- 可选 PostgreSQL + pgvector
- 可选 MinIO
- 可选 Redis
- 一个 OpenAI-compatible 模型 endpoint
- 真实联网搜索时需要 Tavily API key

## 安装

```powershell
Set-Location D:\hollisagent\LLMentor-master\DeepDesk\backend
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

至少配置：

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen3.7-flash-2026-07-15
```

真实联网搜索：

```env
SEARCH_MODE=tavily
TAVILY_API_KEY=...
```

启动：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8888
```

## 配置说明

### 模型

主 Agent：

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=qwen3.7-flash-2026-07-15
OPENAI_TEMPERATURE=0.7
```

Query Rewrite 与 Vision 可使用独立 provider；对应字段为空时自动复用主模型配置：

```env
QUERY_REWRITE_API_KEY=
QUERY_REWRITE_BASE_URL=
QUERY_REWRITE_MODEL=

VISION_API_KEY=
VISION_BASE_URL=
VISION_MODEL=
```

Embedding：

```env
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
EMBEDDING_BATCH_SIZE=9
```

### 搜索

```env
SEARCH_MODE=demo
TAVILY_API_KEY=
TAVILY_ENDPOINT=https://api.tavily.com/search
```

`demo` 适合无外部依赖的本地测试；真实 Deep Research 和 WebSearch 使用 `tavily`。

### 持久化

```env
PERSISTENCE_MODE=memory
DATABASE_URL=
```

- `memory`：适合本地 Agent 演示和单元测试。
- `database`：启用 MySQL-backed session/file/PPT persistence。

本地完整 Workspace 验收可使用仓库根目录的 `docker-compose.fullstack.yml`，其开发变量片段位于 `.env.fullstack.example`。该配置提供 MySQL、PgVector 与 MinIO，`TASK_MANAGER_MODE` 仍可保持 `local`。

数据库模式下可通过 Alembic 初始化：

```powershell
python -m alembic upgrade head
```

### File RAG

```env
LARGE_FILE_THRESHOLD_CHARS=5000
FILE_CHUNK_SIZE_CHARS=500
FILE_CHUNK_OVERLAP_CHARS=50
VECTOR_DATABASE_URL=
VECTOR_TABLE_NAME=vector_file_info
RAG_TOP_K=5
RAG_MULTI_QUERY_COUNT=3
```

未配置 `VECTOR_DATABASE_URL` 时，大文件不会写入向量库；文件 metadata 仍可保留，并可退化到已持久化文本。

### MinIO

```env
MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=rag-test2
MINIO_SECURE=false
```

File/PPT 真实对象存储链路需要可访问的 MinIO。

### Skills

```env
SKILLS_WORKSPACE_ROOT=./agent-workspace
SKILLS_DIRECTORIES=./skills
SKILLS_BASH_ENABLED=false
SKILLS_BASH_ALLOWED_COMMANDS=git
SKILLS_MAX_AGENT_ROUNDS=10
SKILLS_CONTEXT_TOKEN_THRESHOLD=60000
```

FileSystem、Grep 和 Bash 都限制在 `SKILLS_WORKSPACE_ROOT`。Bash 默认关闭。

### Deep Research

```env
DEEP_MAX_ROUNDS=3
DEEP_CONTEXT_CHAR_LIMIT=50000
DEEP_TOOL_CONCURRENCY=3
DEEP_TOOL_RETRIES=2
DEEP_TASK_AGENT_ROUNDS=5
```

`DEEP_TOOL_RETRIES=2` 表示一次初始执行失败后最多额外重试两次。

Deep Research 的 nested task-agent 搜索调用保持内部实现细节；外层 SSE 主要输出研究过程 `thinking`、最终 `text`、`reference` 和 `complete`。

### PPT Builder

```env
PPT_RENDER_SCRIPT_PATH=./resources/python/render_ppt.py
PPT_OUTPUT_DIR=./output/ppt
PPT_RENDER_TIMEOUT_SECONDS=300
PPT_IMAGE_MODEL=qwen-image-plus
```

PPT 完整链路需要：

1. `PERSISTENCE_MODE=database`；
2. 数据库中存在可读取的 PPT 模板；
3. MinIO 可用；
4. 如果需要 AI 图片，图片 provider 可用。

### Redis TaskManager

```env
TASK_MANAGER_MODE=local
REDIS_URL=redis://127.0.0.1:6379/0
TASK_TTL_SECONDS=1800
TASK_TTL_REFRESH_SECONDS=300
```

单实例开发可使用 `local`；多实例部署使用 Redis。

### 鉴权与限流

默认开发配置：

```env
AUTH_MODE=off
RATE_LIMIT_MODE=off
```

生产模式建议启用：

```env
AUTH_MODE=api_key
AUTH_API_KEYS_JSON={"frontend":{"token":"<long-random-token>","scopes":["agent","file","session"]}}
RATE_LIMIT_MODE=redis
```

### 可观测性

健康检查：

- `GET /health`
- `GET /health/live`
- `GET /health/ready`

Prometheus：

- `GET /metrics`

Tracing：

```env
TRACING_ENABLED=false
TRACING_EXPORTER=none
TRACING_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces
```

## SSE Contract

Agent stream 使用统一事件模型：

```text
thinking
text
tool_start
tool_end
reference
recommend
error
complete
```

并非每个 Agent 都会产生所有事件。正常请求必须最终发送 `complete`；错误请求通过 `error` 暴露稳定错误码/消息后结束。

## 测试

运行全部测试：

```powershell
python -m pytest -q
```

静态检查：

```powershell
python -m ruff check .
git diff --check
```

默认测试使用 fake/mock provider 隔离外部网络。真实 Redis、MinIO、PgVector 和 provider 验收通过显式 integration/smoke 测试单独执行。

Workspace 持久化重启验收不调用 LLM；配置真实 `DATABASE_URL` 和 MinIO 后运行：

```powershell
$env:RUN_WORKSPACE_PERSISTENCE_INTEGRATION="1"
python -m pytest -q tests/test_workspace_persistence_integration.py
```

## 当前状态

当前核心链路已经具备真实运行能力：

- 主 Agent Chat / streaming / tool calling：已验证；
- Query Rewrite / MultiQuery：已验证；
- Vision：已验证；
- `text-embedding-v4 / 1024`：已验证；
- Skills：已验证真实模型工具调用；
- Deep Research：已验证真实 Tavily 搜索、reference、final report 和 complete；
- PPT core：已验证模型生成 schema、renderer 子进程、MinIO 上传与可打开 `.pptx`；
- Redis/MySQL/MinIO/PgVector 的本地故障语义已有 contract/integration 覆盖。

进一步工作集中在生产环境配置、真实图片生成链路、长期稳定性与压力测试。详细计划见 [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md)。
