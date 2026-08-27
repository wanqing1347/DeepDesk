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
