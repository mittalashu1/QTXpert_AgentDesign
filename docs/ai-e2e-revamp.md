# QTXpert AI E2E Automation Revamp

## Benchmark conclusion

QTXpert currently stops at structured test-case generation. Testsigma closes the lifecycle: it maps commits and sprint context, proposes smoke/feature/regression/deep-regression plans, executes across web/mobile/API/Salesforce, heals locators, reports coverage and release confidence, and gates releases with human approval. Drizz is narrower but deeper on mobile: plain-English flows are executed on real iOS/Android devices with vision-based interaction, adaptive waits, self-healing, artifacts, CI, and failure explanations.

The strategic gap is not another prompt. It is an execution control plane.

## Target product

1. Ingest requirements, Jira/GitHub changes, Figma/Confluence, OpenAPI/Postman, recordings, and APK/IPA builds.
2. Plan: generate an explicit smoke/feature/regression/deep-regression plan with traceability, risk, expected assertions, and an approval step.
3. Compile approved natural-language cases into an intermediate test representation (ITR), not provider-specific scripts.
4. Execute adapters for Playwright web, REST/OpenAPI, Appium/real-device mobile, and later Salesforce/desktop.
5. Observe: persist step events, screenshots, video, DOM/accessibility snapshots, network logs, device metadata, and model decisions.
6. Heal: detect locator/state drift, propose a confidence-scored patch, rerun the step, and require approval before changing the canonical test.
7. Analyze: deduplicate failures, classify product-vs-environment defects, calculate requirement coverage, flake rate, pass rate, and release confidence.
8. Integrate GitHub Actions/Jenkins/Azure DevOps webhooks, Jira/Linear defect creation, Slack/Teams notifications, and signed webhooks.

## Architecture changes required after this PR

- Move execution from FastAPI in-process background tasks to a durable queue (Redis Streams/Celery or a managed worker) with leases, cancellation, retries, and idempotency keys.
- Add test_plans, test_steps, execution_runs, execution_steps, artifacts, healing_proposals, coverage_edges, and integration_connections tables.
- Store binary artifacts in object storage with tenant-scoped encryption and retention policies; keep only metadata in Postgres.
- Introduce an ITR schema with typed actions (tap, fill, assert_text, request, assert_json, wait_for_state, screenshot, deep_link, restart_app) and an adapter capability matrix.
- Add Playwright first, then API, then mobile device-cloud adapters. Do not claim mobile execution until real-device runs and artifact retrieval are operational.
- Add release-gate policies combining critical-path coverage, pass rate, flaky-test rate, unresolved high-risk failures, and healing confidence.
- Add human approval for generated plans, healing patches, release gates, and external side effects.

## UX principles

- Make the first screen a release workspace: source changes, plan status, coverage, confidence, and blockers.
- Always show why a case exists, what requirement it covers, which adapter will run it, and the evidence behind the result.
- Stream step-level progress and artifacts; never make a user wait on a blank spinner.
- Separate generated, approved, executable, running, healed, and quarantined states.
- Keep a why-failed explanation next to raw logs and screenshots.

## Non-negotiable quality gates

- Every AI output is schema-validated and versioned.
- Every run is idempotent and recoverable after worker restarts.
- No secrets or production credentials enter prompts or artifacts.
- Provider/model parameters are capability-tested, not inferred only from deployment names.
- New adapters ship with contract tests and replayable fixtures.
