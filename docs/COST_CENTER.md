# QTXpert Cost Center

The Cost Center is an owner-only FinOps view available to the active admin account `admin@qtxpert.com`. It combines QTXpert's internal AI meter with a maintained inventory of every external service that can add cost.

## Cost semantics

QTXpert never converts missing billing data into a zero-cost claim.

- **Actual connected** — an authoritative provider billing feed is connected (currently Azure Cost Management when configured).
- **Estimated only** — QTXpert has internal usage/token metering, but not the provider invoice.
- **No billing feed** — the service can incur cost, so the row links directly to its billing portal and documents the known plan limits for manual reconciliation.
- **Not configured** — the service is not detected/configured in the current environment.

Each row now contains a clickable portal name, pricing link, account-plan label (when supplied), documented limits, and any safe live usage returned by a provider connector. Credentials are never persisted in the snapshot or returned to the browser.

## Automatic refresh

The backend stores a non-sensitive `cost_center_snapshots` record in Neon. At startup and when the Cost Center is opened, the snapshot is refreshed only when it is older than `COST_CENTER_REFRESH_DAYS` (30 days by default). The page also exposes **Refresh catalog** for an immediate owner-authorized check. This event-driven schedule avoids a separate always-on worker or paid cron; if the service is continuously running but nobody opens Cost Center, the next startup or open performs the due check.

Enable these Render environment variables on the backend service for account-specific values:

| Variable | Purpose |
| --- | --- |
| `COST_CENTER_AUTO_REFRESH_ENABLED=true` | Enable the monthly stale-snapshot check. |
| `COST_CENTER_REFRESH_DAYS=30` | Refresh interval; increase to reduce provider API calls. |
| `BROWSERSTACK_USERNAME` / `BROWSERSTACK_ACCESS_KEY` | Shows App Automate plan and parallel/queue capacity. |
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` | Shows account-level R2 object and payload metrics. Use a read-only R2 metrics token. |
| `NEON_API_KEY` / `NEON_ORG_ID` | Shows the Neon monthly spending limit. |
| `NEON_PLAN` | Optional non-secret plan label (for example, `Launch`) to display next to Neon. |

Provider probes are bounded and independent. A failed connector changes the catalog to **partial** and leaves the last successful snapshot plus the public portal links visible; it does not fail the Cost Center request.

## Cost surfaces tracked

The inventory covers Azure OpenAI, Gemini, OpenAI, Anthropic, AWS Bedrock, Render backend/frontend, Neon Postgres, Redis/worker infrastructure, Cloudflare R2, BrowserStack, Pinecone, Jira, Confluence, GitHub/Actions, domain/DNS, and upload/test-evidence storage. Optional rows are marked **Not configured** until their integration URL or credentials are present. The list is intentionally a coverage map as well as a spend report, so unknown or manually reconciled amounts remain blank/`Not available` rather than displaying `$0`.

The published figures are reviewed against the provider documentation linked by each row. The current review includes [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/), [Cloudflare R2 limits](https://developers.cloudflare.com/r2/platform/limits/), [Neon pricing](https://neon.com/pricing), [Render free-plan limits](https://render.com/docs/free), and the [BrowserStack App Automate plan API](https://www.browserstack.com/docs/app-automate/api-reference/appium/plan). Provider pricing and account limits can change; the portal link remains the authority for an invoice or contract-specific value.

