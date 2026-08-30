# QTXpert Autopilot — Android Prototype

## Product intent

QTXpert Autopilot is the autonomous mobile Quality Engineering entry point for QTXpert. The target customer journey is:

`APK/IPA → application understanding → minimal context → test strategy → test cases → QTX Test IR → automation → device execution → evidence → RCA → healing → coverage learning → release confidence`

The current prototype establishes the Android vertical slice and safe execution boundary.

## What is implemented

### 1. APK intake and application intelligence

Authenticated users can upload an Android APK (prototype limit 250 MB). QTXpert stores an owner-bound job, computes SHA-256, and uses Androguard to extract:

- application/package/version information
- min/target SDK
- main activity and activities
- services and receivers
- requested permissions
- debug posture
- package file count

### 2. Test-design brain

QTXpert combines deterministic mobile rules with optional enrichment through the existing LLM abstraction. If the LLM is unavailable, deterministic analysis still completes.

The plan includes smoke, lifecycle, semantic UI/accessibility baseline, package-security baseline, network-resilience candidates and permission-specific cases inferred from the APK. AI enrichment adds evidence-supported domain context, critical journeys, risks and additional cases.

### 3. Minimal-context interview

The prototype asks only for information that cannot safely be inferred, such as:

- target environment
- non-production test credentials/roles
- prohibited or approval-only actions
- release-critical journeys
- integrated systems that should be validated

Production secrets should not be pasted into the free-text context field. A dedicated test-data/secret vault is a later milestone.

### 4. QTX Test IR 0.1

Every test design can be compiled through:

`GET /api/v1/autopilot/{job_id}/automation`

The response contains tool-independent semantic steps plus an Appium Python automation artifact.

Each test is explicitly classified as:

- `executable` — enough runtime information already exists to run deterministically
- `discovery_required` — runtime UI/screen mapping is still required before deterministic locators can be emitted
- `approval_required` — business-impacting/destructive action must not run autonomously without policy approval

This prevents QTXpert from fabricating selectors or silently executing risky actions.

### 5. Safe smoke execution

`POST /api/v1/autopilot/{job_id}/smoke`

supports:

- BrowserStack App Automate (preferred cloud prototype path)
- custom/private/local Appium endpoint

The smoke runner starts an Android session, launches the uploaded build, waits for the session to expose a UI hierarchy, captures screenshot and UI hierarchy, records package/activity/orientation, validates that the expected application (rather than a launcher, permission screen, crash or ANR dialog) is foregrounded, and closes the session. It does not execute a business transaction. Unattended safe smoke enables Appium's runtime-permission auto-grant by default; the form can turn it off when permission prompts themselves are under test.

### 6. Durable results and reruns

Autopilot now keeps the complete run chain traceable across page refreshes and Render restarts:

- `autopilot_jobs` in PostgreSQL stores the analysis status, context, generated analysis and the linked APK repository asset.
- `uploaded_assets` plus `uploaded_asset_chunks` stores the original APK and each smoke screenshot/UI-source artifact durably.
- `autopilot_executions` stores the provider/device request, result status, timing, package/activity, error and evidence references.
- `GET /api/v1/autopilot/{job_id}/executions` returns the newest smoke history.
- `POST /api/v1/autopilot/{job_id}/executions/{execution_id}/rerun` repeats a previous smoke with the exact same target settings.
- `POST /api/v1/autopilot/{job_id}/rerun-analysis` creates a new analysis from the original stored APK or a replacement `upload_id`, preserving the previous context unless a new context is supplied.

The Autopilot page exposes both rerun paths: **Rerun** beside a previous smoke repeats its exact provider/device/permission request, while **Rerun this analysis** can reuse the original APK or the stored APK currently selected in the source selector and can use edited context. Every attempt receives a new execution id and its own evidence directory, so reruns never overwrite an earlier result.

The service also writes one JSON record per execution under the job's local `executions/` directory as a degraded-database fallback. On Render, the PostgreSQL/Upload Repository records are the durable source of truth; the local filesystem is only a working copy.

If the PostgreSQL chunk repository is full, a new APK upload now returns `507 Insufficient Storage` with an actionable capacity/object-storage message and removes only the incomplete local job. Existing stored APKs can still be selected for reuse where the repository remains readable.

The current Android analysis consumes the APK, the optional Autopilot context, and any repository documents explicitly selected in the Autopilot document picker. Selected documents are streamed from the shared Upload Repository, redacted for common secret-looking fields, and bounded before they are appended to the analysis context. Unselected documents are never injected implicitly, so each run records exactly which document asset IDs informed it. Document Intelligence and Test Design use the same repository records rather than creating duplicate uploads.

### 7. BrowserStack real-device adapter

When these backend secrets exist:

- `BROWSERSTACK_USERNAME`
- `BROWSERSTACK_ACCESS_KEY`

QTXpert uploads the APK server-side to BrowserStack, caches the returned `bs://` application reference per APK SHA, and starts the Appium session using server-side credentials. No BrowserStack credentials are sent to the browser.

## Setup and first safe smoke run

### BrowserStack real device (hosted Render deployment)

1. Create or open a BrowserStack App Automate account and copy the account username and access key.
2. In the Render Dashboard, open the **backend** service's Environment page and add these as secret values (never commit them):

   - `BROWSERSTACK_USERNAME`
   - `BROWSERSTACK_ACCESS_KEY`

3. Let the backend redeploy. The Autopilot provider status will then report BrowserStack as configured and the BrowserStack option will be enabled.
4. Select **BrowserStack**, choose a supported Android device/OS (the default prototype target is Google Pixel 8 / Android 14.0), and click **Run safe smoke**. The backend uploads the stored APK, starts one real-device Appium session, captures launch evidence, and closes the session.

The smoke is intentionally non-destructive: it installs/cold-launches the build and records a screenshot, UI hierarchy, package, activity and orientation. It does not perform payments, deletion, OTP, notifications or other business mutations. The server-side upload and device session use the configurable limits below, which are deliberately longer for large APKs:

| Setting | Default |
| --- | ---: |
| `AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS` | `300` |
| `AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS` | `120` |
| `AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS` | `120` |
| `AUTOPILOT_SMOKE_TIMEOUT_SECONDS` | `600` |
| `AUTOPILOT_BROWSERSTACK_UPLOAD_TIMEOUT_SECONDS` | `600` |

### Custom/local Appium

On the Android/Appium host, open a new PowerShell window and run:

```powershell
$sdk="$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_HOME=$sdk
$env:ANDROID_SDK_ROOT=$sdk
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
$env:Path="$env:JAVA_HOME\bin;$sdk\platform-tools;$sdk\emulator;$env:Path"

appium driver list --installed
appium --address 127.0.0.1 --port 4723
```

In another PowerShell window, start an available emulator and verify it:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd Pixel_10_Pro_XL -no-snapshot -no-boot-anim -gpu swiftshader_indirect -no-audio
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices -l
```

The local adapter needs an online device (`adb devices` shows `device`), a boot-completed Android system, and an Appium `/status` response with `ready: true`. In the Autopilot form use the emulator id reported by adb (for this verified setup: `emulator-5554`), Android `17`, and `http://127.0.0.1:4723` **only when the QTXpert API is running on the same machine**.

The hosted Render API cannot reach your laptop's `127.0.0.1` and cannot read a local Windows APK path. The hosted UI disables Custom/local Appium until a reachable endpoint is configured, and the API rejects loopback targets before opening a session. For a hosted custom-Appium run, expose Appium through an authenticated TLS tunnel or private reachable endpoint and provide an app reference that the Appium host can read. Keep Appium bound to localhost; do not expose an unauthenticated `0.0.0.0:4723` endpoint.

The verified local run completed successfully with the InvestNation UAT APK on `emulator-5554` / Android 17 and produced launch screenshot/UI-source evidence under the per-run `outputs/local-smoke-runtime-validation/<job-id>/evidence/<execution-id>/` directory. A prior run exposed an Android System UI/launcher ANR; runtime validation now records that as a failed/blocked run instead of reporting a false pass.

### 8. Autopilot workspace

The React workspace is available under `/autopilot` and shows:

- upload/context intake
- application intelligence
- inferred journeys
- clarification questions
- initial release risks
- autonomous test portfolio
- safety/approval status
- BrowserStack/custom-Appium readiness
- safe smoke execution result

## Safety model

The prototype deliberately separates observation from business mutation. Automatic capabilities can inspect packages, launch apps, inspect UI state and capture evidence. Payment, deletion, customer notification, real OTP actions and other irreversible/externally visible operations require a future policy/approval layer.

## Important prototype limitations

This is not yet the final autonomous QA system. The following are intentionally not represented as complete:

1. Full autonomous traversal of every screen and state.
2. Runtime semantic element discovery that resolves all `discovery_required` QTX IR steps.
3. Full generated-suite execution; the production runner currently exposes the safe launch smoke while QTX IR provides the automation boundary.
4. Persistent Application Genome/Digital Twin database.
5. Self-healing, flaky-test intelligence and test-impact analysis.
6. RCA and automatic Jira/Azure DevOps defect creation.
7. MobSF/MASVS security orchestration, performance, visual and full accessibility engines.
8. IPA/iOS signing, provisioning and execution.
9. Dedicated blob/object storage and retention policy for large APKs/evidence. The current PostgreSQL chunk repository is durable but remains a prototype storage backend.
10. Asynchronous long-running workflow orchestration for large suites/device matrices.

## Next engineering slices

### M1 — Runtime Discovery Agent

- capture screen fingerprint (screenshot + hierarchy + package/activity)
- enumerate actionable controls
- assign semantic roles
- detect duplicate states
- maintain visited-state graph
- enforce safe/approval action policy
- emit screen/transition map

### M2 — Deterministic Locator Resolver

- accessibility/resource ID first
- semantic locator second
- visual fallback third
- confidence score and evidence
- convert QTX IR `intent` steps to executable actions

### M3 — Autonomous Suite Runner

- compile executable QTX IR to Appium
- run selected test suites
- parallel device execution
- per-step screenshot/log/evidence
- result normalization

### M4 — Application Genome

Persist in PostgreSQL/graph storage:

- builds
- screens/states
- controls
- transitions
- journeys
- business concepts
- APIs/integrations
- tests
- risks
- defects
- coverage
- execution history

### M5 — Learning/RCA loop

- classify product/test/device/network/data/environment failures
- selector/semantic self-healing
- flakiness scoring
- coverage-gap detection
- automatic new test proposal/generation
- change/test-impact selection

### M6 — Advanced QE

- MobSF + OWASP MASVS/MASTG
- accessibility
- visual regression
- runtime performance/network metrics
- resilience/interruption testing
- localization/device matrix
- release confidence engine

### M7 — iOS

- IPA intake
- Info.plist/entitlement analysis
- signing/provisioning strategy
- Appium/XCUITest execution
- iOS device-cloud adapters

## Production architecture changes before customer pilot

Before treating Autopilot as customer-production ready, move uploaded binaries and evidence from local service storage to durable object storage, persist jobs/Application Genome in PostgreSQL, introduce a secrets vault, execute long-running work in a worker/workflow system, implement retention/expiry rules, and add tenant-level RBAC/auditing.
