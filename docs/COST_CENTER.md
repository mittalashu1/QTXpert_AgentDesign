# QTXpert Cost Center

The Cost Center is an owner-only FinOps view available only to the active admin account `admin@qtxpert.com`.

## Cost semantics

QTXpert never converts missing billing data into a zero-cost claim.

- **Actual connected** — authoritative provider billing is connected (currently Azure Cost Management when configured).
- **Estimated only** — QTXpert has internal usage/token metering, but not the provider invoice.
- **No billing feed** — the platform can incur cost, but QTXpert has no billing connector; reconcile against the provider invoice/portal.
- **Not configured** — the service is not detected/configured in the current environment.

## Cost surfaces tracked

The inventory includes current QTXpert platform surfaces such as Azure OpenAI, Gemini, OpenAI, Anthropic, AWS Bedrock, Render backend/frontend, PostgreSQL, Redis/worker infrastructure, BrowserStack, Pinecone, GitHub/Actions, domain/DNS, and upload/test-evidence storage.

The inventory is intentionally a coverage map as well as a spend report. Unknown or manually reconciled amounts remain blank/`Not available` rather than displaying `$0`.
