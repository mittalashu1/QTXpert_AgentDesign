# Environment Variables Reference

All configuration lives in environment variables (`backend/.env` locally,
Render service environment in production). See `backend/.env.example` for
a ready-to-copy template. Full reference:

## General
| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | QTXpert.ai Test Design Agent | Display name |
| `APP_ENV` | local | `local` \| `development` \| `staging` \| `production` |
| `DEBUG` | false | Verbose error responses |
| `LOG_LEVEL` | INFO | Python logging level |
| `CORS_ORIGINS` | localhost origins | Comma-separated allowed origins |

## Database / Cache
| Variable | Description |
|---|---|
| `POSTGRES_URL` | Async SQLAlchemy URL, e.g. `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection string (rate limiting backend, future Celery broker) |

## Auth
| Variable | Description |
|---|---|
| `JWT_SECRET` | Signing secret - set a long random value in production |
| `JWT_ALGORITHM` | Default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default 60 |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | Default 10080 (7 days) |
| `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` / `ENTRA_CLIENT_SECRET` | Optional Microsoft Entra ID SSO |

## LLM Provider Selection
| Variable | Description |
|---|---|
| `LLM_PROVIDER` | One of `router` (default), `azure_openai`, `openai`, `anthropic`, `gemini`, `bedrock` |
| `LLM_MODEL` | Model/deployment name used by whichever provider is active |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_REQUEST_TIMEOUT_SECONDS` | Generation tuning |
| `LLM_ROUTER_LOW_COST`, `LLM_ROUTER_STANDARD`, `LLM_ROUTER_COMPLEX`, `LLM_ROUTER_FALLBACK` | Comma-separated `provider:model` routes used for cost-first routing and fallback |
| `LLM_ROUTER_COMPLEX_INPUT_CHARS` | Input length at which the router starts at the complex tier (default `30000`) |
| `LLM_COST_RATES_JSON` | JSON map of `provider:model` to per-million-token `input`/`output` USD rates; powers admin cost estimates |

Per-provider credentials (only the active provider's keys are required):

| Provider | Required variables |
|---|---|
| Azure OpenAI | `AZURE_OPENAI_API_KEY`, `AZURE_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Gemini | `GOOGLE_API_KEY` |
| Bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `BEDROCK_MODEL_ID` |
## AWS Application Performance Monitoring (optional)

The Render backend includes opt-in AWS Distro for OpenTelemetry support for
CloudWatch Application Signals and X-Ray. It is disabled by default and does
not change the normal startup path until `AWS_APM_ENABLED=true` is set.

| Variable | Default | Description |
|---|---|---|
| `AWS_APM_ENABLED` | `false` | Starts the ADOT Python auto-instrumenter when `true`. |
| `AWS_APM_SERVICE_NAME` | `qtxpert-backend` | Service name shown in CloudWatch Application Signals. |
| `AWS_APM_ENVIRONMENT` | `production` | Deployment environment dimension. |
| `AWS_APM_TRACE_SAMPLE_RATIO` | `0.05` | Trace sampling ratio; keep bounded to control ingestion cost. |
| `AWS_APM_LOG_GROUP` / `AWS_APM_LOG_STREAM` | unset | Existing CloudWatch Logs group/stream for correlated logs. If either is unset, log export stays off while traces continue. |
| `OTEL_METRICS_EXPORTER` | `none` | Metrics are off by default to avoid duplicate Application Signals ingestion; Render native metrics remain available. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | derived | Optional X-Ray OTLP endpoint override; otherwise `https://xray.$AWS_REGION.amazonaws.com/v1/traces`. |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | derived | Optional CloudWatch OTLP logs endpoint override. |

See [`docs/AWS_APM.md`](AWS_APM.md) for the IAM policy, Render secret setup,
and validation checklist. Do not reuse an unrestricted Bedrock or root key for
telemetry; use a dedicated least-privilege role/key and rotate it.

Successful model calls are persisted for the admin-only Dashboard AI spend card.
Run the database migration (`alembic upgrade head`) before enabling production
usage reporting. Costs are estimates from `LLM_COST_RATES_JSON`; token usage is
still shown when a model has no configured rate.

## Vector Database (optional, modular)
| Variable | Description |
|---|---|
| `VECTOR_DB_PROVIDER` | `pinecone` or `none` (default) |
| `PINECONE_API_KEY`, `PINECONE_ENVIRONMENT`, `PINECONE_INDEX_NAME` | Required only if provider is `pinecone` |

## Jira / Confluence (optional, for Methods 3 & 4)
| Variable | Description |
|---|---|
| `JIRA_URL`, `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `JIRA_REDIRECT_URI` | Jira Cloud OAuth2 app credentials |
| `CONFLUENCE_URL`, `CONFLUENCE_CLIENT_ID`, `CONFLUENCE_CLIENT_SECRET`, `CONFLUENCE_REDIRECT_URI` | Confluence Cloud OAuth2 app credentials |

## Uploads / Rate limiting
| Variable | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE_MB` | 25 | Per-file readable document limit (BRD/export/test-data text inputs) |
| `AUTOPILOT_MAX_UPLOAD_SIZE_MB` | 250 | Per-file APK/IPA limit shared by Autopilot and Design app-source uploads |
| `ALLOWED_UPLOAD_EXTENSIONS` | pdf,docx,txt,md,json,csv,… | Accepted document, test-data, media and APK/IPA formats |
| `UPLOAD_STORAGE_BACKEND` | postgres_chunks | Shared Upload Repository backend (`postgres_chunks` for compatibility or `object_store` for R2/S3-compatible storage) |
| `UPLOAD_STORAGE_PATH` | ./storage/uploads | Local working path used by the repository fallback; repository metadata and bytes remain project-scoped and reusable |
| `RATE_LIMIT_PER_MINUTE` | 60 | Per-client-IP request budget |

## Frontend (`frontend/.env`)
| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend API base URL (`/api/v1` locally via Vite proxy, full URL in production) |
