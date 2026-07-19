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
| `LLM_PROVIDER` | One of `azure_openai` (default), `openai`, `anthropic`, `gemini`, `bedrock` |
| `LLM_MODEL` | Model/deployment name used by whichever provider is active |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_REQUEST_TIMEOUT_SECONDS` | Generation tuning |

Per-provider credentials (only the active provider's keys are required):

| Provider | Required variables |
|---|---|
| Azure OpenAI | `AZURE_OPENAI_API_KEY`, `AZURE_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Gemini | `GOOGLE_API_KEY` |
| Bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `BEDROCK_MODEL_ID` |

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
| `MAX_UPLOAD_SIZE_MB` | 25 | Per-file upload limit |
| `ALLOWED_UPLOAD_EXTENSIONS` | pdf,docx,txt,md,json,csv | Accepted BRD/export formats |
| `UPLOAD_STORAGE_PATH` | ./storage/uploads | Local scratch path (uploads are processed then discarded; nothing is persisted to disk beyond this) |
| `RATE_LIMIT_PER_MINUTE` | 60 | Per-client-IP request budget |

## Frontend (`frontend/.env`)
| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend API base URL (`/api/v1` locally via Vite proxy, full URL in production) |
