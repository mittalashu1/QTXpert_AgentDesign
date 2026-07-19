# Deployment Guide (Render)

This repo includes `render.yaml` at the root, defining a Render Blueprint
with two web services (backend, frontend), a managed Postgres database, and
a managed Redis instance.

## Steps

1. Push this repo to GitHub.
2. In the Render dashboard: **New > Blueprint**, connect the repo, and
   Render will read `render.yaml` and propose the services.
3. Before the first deploy, set these secrets on the **qtxpert-backend**
   service (Render dashboard > Environment) - they're intentionally left
   out of `render.yaml`:
   - At minimum, whichever provider matches `LLM_PROVIDER`:
     - Azure OpenAI: `AZURE_OPENAI_API_KEY`, `AZURE_ENDPOINT`,
       `AZURE_OPENAI_DEPLOYMENT`
     - OpenAI: `OPENAI_API_KEY`
     - Anthropic: `ANTHROPIC_API_KEY`
     - Gemini: `GOOGLE_API_KEY`
     - Bedrock: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
   - Optional: `PINECONE_API_KEY`, `PINECONE_ENVIRONMENT` (only if
     `VECTOR_DB_PROVIDER=pinecone`)
   - Optional: `JIRA_*` / `CONFLUENCE_*` if using live Jira/Confluence
     connections
4. Deploy. Render provisions Postgres/Redis and injects their connection
   strings automatically (`POSTGRES_URL`, `REDIS_URL`).
5. On every deploy, the backend container runs `alembic upgrade head`
   before starting Uvicorn (see `backend/Dockerfile`'s `CMD`), so schema
   migrations are applied automatically.
6. Update `CORS_ORIGINS` on the backend service, and
   `VITE_API_BASE_URL` on the frontend service, once you know your final
   Render service URLs (or custom domains).

## Rolling back

Render keeps prior deploys; use **Manual Deploy > Rollback** on the
affected service. Database migrations are additive (no destructive
downgrade is run automatically) - if a migration must be reverted, run
`alembic downgrade -1` manually via a Render shell against that service.

## Scaling

- Backend: increase the Render plan/instance count; the app is stateless
  (JWT auth, no in-memory session), so horizontal scaling works without
  code changes once the rate limiter is swapped to the Redis-backed
  implementation described in `app/api/middleware.py`.
- Database/Redis: upgrade the managed plan from the Render dashboard.
