# QTXpert Design Version 1 baseline

Version 1 is tagged `v1.0.0` at commit `3404bc39b244ae9ab1695947516de78fe2272796`.
This commit is live on the Render frontend and backend, and its CI run passed.
[GitHub release](https://github.com/mittalashu1/QTXpert_AgentDesign/releases/tag/v1.0.0) ·
[Baseline branch](https://github.com/mittalashu1/QTXpert_AgentDesign/tree/release/v1.0.0) ·
[CI results](https://github.com/mittalashu1/QTXpert_AgentDesign/actions/runs/45320812413)

The InvestNation Android verification passed nine targeted cases. Six shared one
sign-in. Discovery recorded 101 screen states and 348 transitions, with 203
candidate actions still open at the action limit. A later sign-in stalled before
the device idle-timeout check could run. The Design portal passed ten local route
checks and a sample through execution and reporting with a fixed model response.

## Next phase

1. **Make Android repeatable from the Design portal.** A prompt and uploaded APK
   should start on the paired USB device, reuse authorized app-scoped Test Data,
   and reach a report. Preserve the graph and unfinished work through a crawl
   limit or device interruption. Verify sign-in and session recovery, explore
   both ordinary prompt choices, and continue independent branches when a
   journey needs a credential, OTP, or other input.
2. **Verify business outcomes.** Provide isolated UAT accounts that expose Add
   Money and Send Money, with seeded data and cleanup. For each supported
   positive or negative case, define the expected UI response and the evidence
   that proves the posted or rejected outcome. Link receipts or transaction IDs
   to an independent check of persisted state.
3. **Prove the full Design workflow.** Take a real requirement through Document
   Intelligence, Test Design, Execution, and Reports. Bind the generated case
   to its test data and execute it as generated. Carry the requirement, app
   build, device, and verification evidence to each recorded verdict. Repeat on
   iOS and authenticated web after the Android path is repeatable.

The proposed Android pilot covers 30 agreed priority journeys across three
independent portal runs of the same build and prompt. Each critical journey
needs a verified verdict. The pilot targets at least 95% conclusive results and
zero false passes on deliberately failing checks. Any remaining journey records
the specific missing input, route, or outcome evidence.

## Development foundation

- Autopilot and Test Execution can select an online Android device from the
  project's paired runner. Start the updated runner on the paired Windows
  host before the pilot. It downloads the exact repository APK and uses
  loopback Appium. An existing pairing can be reused.
- Document Intelligence and Test Design cases carry structured automation when
  the source supplies exact controls and assertions. Test Execution binds
  reusable encrypted inputs for the selected repository build or website URL.
  Report results retain the document, requirement, design case, build and device.
- Add Money and Send Money require isolated accounts, a seed and cleanup
  reference, an expected UI assertion and a dedicated receipt or attempt-ID
  control. Prepare the accounts and ledger exporter in UAT before the pilot.
  The exporter should have read-only access to authoritative UAT records.

Set `UAT_LEDGER_VERIFICATION_KEY` on the API and on the trusted UAT exporter.
Use a shared secret of at least 32 characters. For each result, the exporter
signs an object containing `schema: "qtx-uat-ledger/1"`, `project_id`, `run_id`,
`result_id` and `evidence`. The evidence contains the captured `reference`,
`source_record`, `operation`, `account_alias`, `seed_reference`, `cleanup_reference`,
`decision`, `posted_count`, `amount_minor`, `currency`, `decision_at` and
`observed_at`. Use UTC timestamps in RFC 3339 format. Serialize sorted keys
with comma and colon separators, no spaces and ASCII escapes. Sign those
bytes with HMAC-SHA256 and include the lowercase hex `signature` in the
evidence JSON imported from Test Reports. A rejected outcome requires a
correlated rejection and zero postings. The ledger observation must be made
after the decision and before fixture cleanup removes the records.
