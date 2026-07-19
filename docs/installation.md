# Installation Guide

## Prerequisites

- Docker and Docker Compose (recommended path), or
- Python 3.12 + Node.js 20 + a local PostgreSQL 16 and Redis 7 instance

## Option A - Docker Compose (recommended)

```bash
git clone <your-repo-url> QTXpert.ai
cd QTXpert.ai
cp backend/.env.example backend/.env
# Edit backend/.env: set LLM_PROVIDER and the matching provider's API key
docker compose up --build
```

Services:
| Service  | URL                              |
|----------|-----------------------------------|
| Frontend | http://localhost:5173             |
| Backend  | http://localhost:8000             |
| API docs | http://localhost:8000/api/docs    |
| Health   | http://localhost:8000/api/v1/health |

## Option B - Run natively

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: point POSTGRES_URL/REDIS_URL at your local instances
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## First-time setup

1. Register a user: `POST /api/v1/auth/register`
2. Log in through the frontend, or `POST /api/v1/auth/login` for a token pair
3. Create a project from the Dashboard
4. Upload a BRD, Jira export, or submit a direct prompt under
   Requirement Upload
5. Run Generate Test Cases
6. Export in whichever format your test management tool needs

## Running tests

```bash
cd backend
pytest --cov=app
```

```bash
cd frontend
npm run lint
npm run build
```
