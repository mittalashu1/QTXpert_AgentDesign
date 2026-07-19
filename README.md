# QTXpert.ai - AI Test Design Agent

Enterprise AI Quality Engineering Platform. This module generates
enterprise-grade software test cases from BRDs, Jira/Confluence exports or
live connections, and direct prompts, using a configurable LLM provider
(Azure OpenAI, OpenAI, Anthropic Claude, Google Gemini, or AWS Bedrock).

## Architecture

```
Frontend (React/MUI) -> API Gateway (FastAPI) -> Test Design Service
   -> Agent Layer (LangGraph) -> Prompt Layer -> LLM Gateway (provider abstraction)
   -> Knowledge Layer (Postgres + optional Pinecone) -> Database
```

Monorepo layout:

```
QTXpert.ai/
  frontend/            React 18 + TypeScript + MUI
  backend/
    app/
      agents/          LangGraph workflow (Test Design Agent)
      llm/             Provider-agnostic LLM abstraction
      integrations/    Jira / Confluence OAuth2 clients
      exports/         JSON/CSV/Excel/Markdown/TestRail/Zephyr/Xray/ADO exporters
      api/routes/      FastAPI routers
      database/        SQLAlchemy models + repositories
      services/        Document processing, generation orchestration
    alembic/           Database migrations
    tests/
  docker-compose.yml
  render.yaml
  .github/workflows/ci.yml
```

## Local development

Prerequisites: Docker and Docker Compose.

```bash
cp backend/.env.example backend/.env
# edit backend/.env - at minimum set an LLM provider's API key and
# LLM_PROVIDER to match it (default: azure_openai)

docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/api/docs
- Health check: http://localhost:8000/api/v1/health

Database migrations run automatically on backend container start
(`alembic upgrade head`). To create a new migration after changing models:

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
```

### Running without Docker

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
cp .env.example .env
npm install
npm run dev
```

## Configuration

All configuration is environment-driven - see `backend/.env.example` for
every key (LLM providers, Jira/Confluence OAuth, Pinecone, JWT, rate
limiting, upload limits). The active LLM provider is selected purely via
`LLM_PROVIDER`; no provider is hardcoded anywhere in the codebase.

## Deployment (Render)

`render.yaml` defines two web services (backend, frontend), a managed
Postgres database, and a managed Redis instance. After connecting the repo
in the Render dashboard:

1. Render provisions Postgres/Redis and wires their connection strings into
   the backend automatically.
2. Set the remaining secrets (LLM provider keys, Jira/Confluence
   credentials, Pinecone) directly in the Render dashboard - they are
   intentionally left out of `render.yaml`.
3. Push to `main` to deploy; the backend runs `alembic upgrade head`
   automatically on container start.

## Testing

```bash
cd backend
pytest --cov=app
```

## Extending with future agents

New agents (Requirement Intelligence, Automation Intelligence, Automation
Script Generator, Defect Prediction, Test Execution Intelligence, AI Test
Manager) can be added as new modules under `backend/app/agents/`, sharing
this repo's auth, database models, and LLM abstraction without
refactoring existing code.
