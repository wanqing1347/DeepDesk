# DeepDesk

**DeepDesk — Agentic Workspace for Research and Knowledge Work**

DeepDesk 是一个面向研究与知识工作的全栈 AI Agent 工作台。项目采用 monorepo 结构，后端基于 FastAPI，前端基于 Vue 3 + Vite + TypeScript。

## 核心能力

- Chat：通用对话与流式响应
- Web Search：Tavily 真实联网搜索与来源引用
- Deep Research：需求分析、规划、执行、评审、最终报告与 Sources
- File Intelligence：文件上传、解析、File RAG、Vision
- Skills Agent：Skill discovery、Tool Calling、本地受限工具
- PPT Agent：CREATE / MODIFY / RESUME、研究、生成、修改与输出
- Platform：Session、TaskManager、认证、限流、Metrics、Tracing、健康检查

## Monorepo 结构

```text
DeepDesk/
├── backend/    # FastAPI multi-agent backend
├── web/        # Vue 3 frontend
├── .gitignore
└── README.md
```

### Backend

```text
backend/
├── app/
├── tests/
├── alembic/
├── resources/
├── pyproject.toml
├── .env.example
├── README.md
└── MIGRATION_PLAN.md
```

### Web

```text
web/
├── src/
├── e2e/
├── package.json
├── vite.config.ts
├── playwright.config.ts
├── README.md
└── FRONTEND_IMPROVEMENT_PLAN.md
```

## 本地开发

### 1. 启动后端

```powershell
Set-Location D:\hollisagent\LLMentor-master\DeepDesk\backend
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8888
```

真实联网搜索需要：

```env
SEARCH_MODE=tavily
TAVILY_API_KEY=...
```

### 2. 启动前端

另开一个终端：

```powershell
Set-Location D:\hollisagent\LLMentor-master\DeepDesk\web
npm install
npm run dev
```

Vite 本地开发默认通过 `/api` 代理后端 `http://127.0.0.1:8888`。

### 3. Full-stack 持久化模式

Workspace Library（Session、File、Presentation）需要数据库模式。仓库提供独立的本地基础设施配置，不会覆盖现有 `backend/.env`：

```powershell
Set-Location D:\hollisagent\LLMentor-master\DeepDesk
docker compose -f docker-compose.fullstack.yml up -d

Set-Location backend
$env:PERSISTENCE_MODE="database"
$env:DATABASE_URL="mysql+pymysql://deepdesk:deepdesk_dev@127.0.0.1:3307/deepdesk?charset=utf8mb4"
$env:MINIO_ENDPOINT="http://127.0.0.1:9000"
$env:MINIO_ACCESS_KEY="deepdesk"
$env:MINIO_SECRET_KEY="deepdesk_dev_secret"
$env:MINIO_BUCKET="rag-test2"
$env:MINIO_PUBLIC_READ="true"
$env:VECTOR_DATABASE_URL="postgresql+psycopg://deepdesk:deepdesk_dev@127.0.0.1:5434/deepdesk_vectors"
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8888
```

这些凭据只用于本地 Docker 开发。完整变量片段见 `backend/.env.fullstack.example`。

可用不调用 LLM 的持久化验收测试验证 App 重建后资产仍然存在：

```powershell
$env:RUN_WORKSPACE_PERSISTENCE_INTEGRATION="1"
python -m pytest -q tests/test_workspace_persistence_integration.py
```

## 质量检查

Backend：

```powershell
Set-Location backend
python -m ruff check .
python -m pytest -q
git diff --check
```

Web：

```powershell
Set-Location web
npm run test
npm run typecheck
npm run lint
npm run build
$env:PLAYWRIGHT_CHANNEL="msedge"
npm run e2e
```

## 项目标识

- 产品：`DeepDesk`
- Backend package：`deepdesk-backend`
- Frontend package：`deepdesk-web`
- OpenTelemetry service：`deepdesk-backend`
- Prometheus namespace：`deepdesk_*`
- Tracing attributes：`deepdesk.*`

前后端通过现有 API contract 与 Canonical SSE 协议协作，主要 Agent 路由保持稳定。
