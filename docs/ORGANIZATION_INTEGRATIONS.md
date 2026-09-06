# Organization integrations and settings boundary

## What an enterprise customer expects

An organization normally wants one governed place to connect the systems that
hold requirements, source changes, test cases, runtime data, and evidence:

| System boundary | Typical sources | QTXpert use | Minimum safe permission |
| --- | --- | --- | --- |
| Work tracking | Jira, Azure Boards, Linear | Import stories/acceptance criteria; create evidence-linked defect drafts | Read; issue-create only when explicitly enabled |
| Knowledge | Confluence, SharePoint, approved document stores | Feed Document Intelligence and preserve source/version lineage | Read selected spaces/sites |
| Source control | GitHub, GitLab, Azure Repos | Change-aware coverage, pull/merge request context, CI callbacks | Read selected repositories; webhook verification |
| Quality systems | TestRail, Xray, Zephyr, customer test repository | Import versioned cases and publish results without replacing the source of truth | Read/write selected project or suite |
| Application data | OpenAPI/GraphQL, read-only database, event/oracle API | Contract checks, data assertions, reconciliation, test-data discovery | Read-only non-production endpoint/schema |
| Evidence and notifications | S3/R2/Azure Blob, Slack/Teams | Private evidence storage, retention, approval/run notifications | Write evidence prefix; channel-scoped notifications |

The important distinction is between *context* integrations (safe reads used to
design or explain tests), *execution* integrations (controlled calls used by a
test), and *mutation* integrations (creating Jira defects or changing data).
Mutation integrations must be disabled by default and approval-gated.

## Settings information architecture

The settings skeleton now has three user-facing areas:

1. **Overview** — current workspace boundary, connector count, configured count,
   the current user's role, and links to API configuration and user
   administration.
2. **Integrations** — a catalog of Jira, Confluence, GitHub, GitLab, Azure
   DevOps, test-case repositories, REST/GraphQL APIs, read-only databases,
   object storage, and Slack. A manager can save organization- or
   project-scoped metadata, select least-privilege scopes, and see a clear
   not-configured/needs-auth/ready-for-test state.
3. **My preferences** — the user's preferred connector, notification policy,
   and timezone. These settings are separate from organization connections.

Organization connections are currently bounded by the authenticated account's
`owner_id`; project-scoped rows additionally require an owned project. This is
intentional: the existing product does not yet have an organization/member
table. The next access-control milestone can introduce `organizations`,
`organization_members`, and `project_members` while keeping this connector
contract stable.

## Connector lifecycle

```text
discover catalog
  -> manager enters non-secret metadata and an opaque secret reference
  -> local validation + audit event
  -> explicit enablement
  -> provider adapter resolves secret in a secret manager
  -> bounded test connection (timeout, retry, redacted error)
  -> approve a sync/read/write capability
  -> scheduled or event-driven sync with lineage and idempotency
```

The current “Test configuration” action stops after local validation and makes
no external request. That distinction is visible in the API response and UI so
an unconfigured connector cannot be mistaken for a healthy remote connection.

## Credential and data rules

- Never send or persist raw API keys, PATs, OAuth refresh tokens, database
  passwords, webhook secrets, or bearer headers in this app's database.
- Store only an opaque reference such as `vault://qtxpert/jira/prod` or
  `env://JIRA_TOKEN`; resolve it inside a provider adapter just before a call.
- Store provider URL, tenant/workspace, project/repository identifiers, scopes,
  and non-sensitive notes as metadata. Sensitive-looking keys are rejected at
  the API boundary.
- Prefer OAuth 2.0, workload identity, GitHub Apps, mTLS, or short-lived
  tokens. PATs must be fine-grained, expiry-bound, and read-only unless a
  specific mutation capability is approved.
- Database integrations must be read-only, non-production by default, with
  schema/table allow-lists, query timeouts, row limits, and value redaction.
- Every create/update/test/delete and future sync is an audit event. Connector
  errors are bounded and sanitized before being displayed to users.
- Evidence remains in the existing private Upload Repository/object store;
  integrations store references and lineage, not duplicate binary content.

## Reference pattern and implementation comparison

TestSigma's public documentation uses a Settings → Integrations model: Jira
is enabled with an account URL/user/API key, Confluence uses an Atlassian
consent flow, and GitHub connects an organization/repository and shows a
connected state. QTXpert follows that familiar discover → configure → verify
shape, but keeps the first release deliberately safer: the form accepts only a
secret-manager reference and the verify button makes no remote mutation until
an adapter and capability approval exist.

- [TestSigma Jira integration](https://testsigma.com/docs/atto/generative-ai/integrations/jira/)
- [TestSigma Confluence integration](https://testsigma.com/docs/test-management/integrations/confluence/)
- [TestSigma GitHub connection](https://testsigma.com/docs/test-management/qi-home/context-mapping/connect-github/)
- [TestSigma GitHub agentic integration](https://testsigma.com/docs/atto/generative-ai/integrations/github/)

## Next implementation milestones

### Connector adapters

Create a common adapter interface (`authorize`, `test`, `pull_context`,
`push_result`, `create_issue`) with provider-specific implementations. The
adapter receives a typed connection and a secret resolver, never a raw secret
from the browser. Add OAuth callback/state/PKCE for Atlassian, GitHub Apps, and
Microsoft; add signed webhook endpoints with replay protection.

### Organization and project access

Add an organization tenant and membership model. Map admin, QA lead, engineer,
analyst, and viewer roles to connection capabilities; allow project managers to
grant a connection to a project without granting access to every project.
Replace owner-only checks in existing project routes with a shared access
dependency and keep deny-by-default behavior.

### Durable sync and observability

Run syncs in a queue/worker with idempotency keys, cursors, rate-limit handling,
dead-letter retries, lineage links to source versions, and a “last successful
sync” dashboard. Meter calls through the existing cost-first model router and
retain only bounded excerpts in Postgres.

### Release gates

Before enabling a write connector, require admin approval, a dry-run preview,
least-privilege scope review, secret rotation/expiry, and a rollback path. Add
contract tests against provider sandboxes and redact connector payloads in
logs.
