# Docs

- `openapi.json` - generated directly from the running FastAPI app
  (`app.openapi()`). Regenerate after changing any route/schema:
  ```bash
  cd backend
  python -c "import json; from app.main import app; json.dump(app.openapi(), open('../docs/openapi.json', 'w'), indent=2)"
  ```
  It's also always live at `/api/openapi.json` on a running instance.
- `postman_collection.json` - converted from `openapi.json` via
  `openapi-to-postmanv2`. Import both this and
  `postman_environment.local.json` into Postman, select the environment,
  then run `POST /auth/login` and copy `access_token`/`refresh_token` into
  the environment variables (or wire a Postman test script to do it for
  you) before calling authenticated routes.
- `installation.md` - local setup steps.
- `deployment.md` - Render deployment steps.
- `environment.md` - full reference for every environment variable.
