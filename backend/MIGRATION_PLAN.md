# DeepDesk Backend 开发计划

> 最后更新：2026-08-25

本文档记录 `DeepDesk/backend` 的功能状态、质量基线和后续工程任务。后端作为 DeepDesk monorepo 的 FastAPI 服务维护，验收以自身 API contract、回归测试、真实 provider 集成和生产可靠性为准。

## 1. 项目目标

提供一个可独立部署的多 Agent 服务，覆盖：

- WebSearch Agent；
- File Agent 与 File RAG；
- Skills Agent；
- Deep Research；
- PPT Builder；
- 会话与文件持久化；
- 多实例任务管理；
- 鉴权、限流、可观测性与故障降级。

核心原则：

1. API 与 SSE contract 稳定；
2. 外部 provider 可替换；
3. 本地开发可以最少依赖运行；
4. 生产模式对硬依赖 fail-closed，对能力级软依赖明确 degraded；
5. 每个重要行为必须有 unit / contract / integration regression；
6. 不用 mock 结果代替真实 provider 或基础设施验收。

## 2. API Contract

### Agent

- `GET /agent/chat/stream`
- `GET /agent/file/stream`
- `GET /agent/skills/stream`
- `GET /agent/deep/stream`
- `GET /agent/pptx/stream`
- `GET /agent/stop`

Agent stream 使用 Canonical SSE：

- `thinking`
- `text`
- `tool_start`
- `tool_end`
- `reference`
- `recommend`
- `error`
- `complete`

不同 Agent 只发送自身实际需要的事件。所有正常或可恢复错误路径都必须有明确终态。

### File

- `POST /file/upload`
- `GET /file/info/{file_id}`
- `GET /file/content/{file_id}`
- `DELETE /file/{file_id}`
- `GET /file/list`
- `GET /file/exists/{file_id}`

### Session

- `GET /session/list`
- `GET /session/{conversation_id}`
- `DELETE /session/{conversation_id}`

### Health / Observability

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`

## 3. 已完成能力

### WebSearch

- OpenAI-compatible streaming；
- Tavily REST / demo search；
- 多 tool-call 并发；
- tool result 回注；
- force-final；
- reference / recommendation；
- persistent memory；
- stop / cancellation。

### File Management + RAG

- PDF / DOCX / TXT 文本解析；
- 常见图片 Vision 描述；
- 小文件 direct-text；
- 大文件 PgVector；
- `500 chars / 50 overlap` splitter；
- Query Rewrite；
- MultiQuery，默认 3 个扩展 query；
- `topK=5`；
- embedding `text-embedding-v4 / 1024` 已完成真实验收；
- 向量化失败保持文件可用并回退 direct-text；
- 删除流程覆盖 metadata / vector / object storage 一致性。

### Skills

- skill discovery；
- `read_skill`；
- WebSearch / FileContent；
- sandboxed filesystem / grep / bash；
- ContextCompactor；
- provider retry；
- persistent memory；
- recommendation；
- stop。

### Deep Research

- requirement clarification；
- research topic generation；
- structured plan；
- 同 order bounded concurrency；
- task dependency context；
- web search tool loop；
- `DEEP_TOOL_RETRIES`；
- critique；
- context compression；
- max rounds；
- streaming final report；
- reference aggregation；
- persistent session；
- cancellation propagation；
- 真实 `qwen3.7-plus + Tavily REST` 搜索、reference、final report、complete 已验收。

Deep Research 的 nested search 调用属于内部研究执行细节，外层 SSE 不发送 `tool_start/tool_end`；该 contract 已有回归测试锁定。

### PPT Builder

- CREATE / MODIFY / RESUME；
- requirement / search / outline / template / schema / render 状态机；
- SQL persistence；
- `qwen-image-plus` adapter；
- image best-effort；
- `render_ppt.py` 子进程渲染；
- timeout / cancellation；
- MinIO upload；
- 已完成文本型 PPT core 真实链路验收，可生成并重新打开 `.pptx`。

### Production Hardening

- SQLAlchemy pooling；
- provider HTTP pooling；
- retry/backoff；
- structured access log；
- request context；
- liveness / readiness；
- graceful shutdown；
- Prometheus metrics；
- OpenTelemetry tracing；
- local / Redis rate limit；
- Bearer API-key + scope；
- CORS / secret startup hardening；
- local / Redis TaskManager；
- Redis 多实例互斥、TTL refresh、Pub/Sub stop；
- MySQL / Redis 硬依赖故障 fail-closed；
- PgVector / MinIO 能力级 degraded。

## 4. 测试体系

### Unit / Contract

重点覆盖：

- SSE schema 与终态；
- tool-call 合并与并发；
- persistence；
- File RAG splitter / metadata / query rewrite；
- Skills sandbox；
- Deep Research 状态机；
- PPT 状态机；
- TaskManager；
- authentication / authorization；
- rate limit；
- metrics / tracing；
- failure-mode contracts。

### Integration

真实集成测试按需启用，覆盖：

- MySQL；
- Redis；
- MinIO；
- PgVector；
- OpenTelemetry Collector；
- LLM / Vision / Embedding provider；
- Tavily；
- PPT renderer。

默认测试不要求联网或外部基础设施。

### Regression Contract

`tests/golden/` 只记录项目自身稳定行为 contract，用于防止关键参数、SSE 时间线和状态机语义被无意改变。它不依赖外部工程基线。

## 5. 当前质量基线

最近已知本地基线：

- `ruff check .` 通过；
- `python -m pytest -q`：`178 passed, 11 skipped`；
- `git diff --check` 通过。

清理或新增代码后必须重新执行全量基线。

## 6. 当前待办

优先级从高到低：

1. 完成 `qwen-image-plus -> image download -> MinIO -> PPT render` 真实图片链路验收；
2. 增加 Deep Research 搜索 provider 全失败时的显式回归覆盖；
3. 进行长期运行、并发与压力测试；
4. 使用生产等价 MySQL / Redis / PgVector / MinIO 做故障演练；
5. 完善部署文件、启动文档和环境变量模板；
6. 收敛测试 warning、临时目录权限和依赖 deprecation；
7. 建立发布前 smoke checklist。

## 7. Definition of Done

服务达到可发布状态需要同时满足：

- 所有公开 API 有自动化 contract；
- Agent SSE 无悬挂流，终态一致；
- 核心 provider 有真实验收记录；
- File / Session / PPT 持久化有真实数据库验收；
- Redis 多实例任务语义通过；
- readiness 与故障降级符合部署预期；
- secrets、CORS、auth、rate limit 满足生产配置要求；
- 全量 pytest、ruff、diff-check 通过；
- 关键链路有可重复 smoke test。
