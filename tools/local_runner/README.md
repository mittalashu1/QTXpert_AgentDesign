# QTXpert local Android runner

The runner connects a project in QTXpert to an Android device or emulator on a
Windows laptop. It polls the QTXpert API over outbound HTTPS; no inbound port,
public IP, SSH tunnel, or public Appium endpoint is needed. Appium must listen
only on `127.0.0.1:4723`.

## Requirements

- Windows 10/11 and Python 3.10+
- Node.js and Appium 3 with the UiAutomator2 driver
- Android SDK Platform Tools (`adb`) on `PATH`
- One Android device/emulator in `adb devices -l` with state `device`
- A paired project runner and a logged-in user able to create Test Execution runs
- Python 3.10+ available as `py -3` or `python` for the one-time setup

Check the local stack from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_runner/setup.ps1
```

If Python is installed outside `PATH`, supply its executable explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_runner/setup.ps1 -PythonPath "C:\path\to\python.exe"
```

Create a one-time enrollment token in Test Execution → Local device runner →
Pair this laptop. From the repository root, use the command the page provides.
It has this shape:

```powershell
tools/local_runner/.venv/Scripts/python.exe tools/local_runner/agent.py pair --api-url "https://design.qtxpert.com/api/v1" --token "ONE_TIME_TOKEN"
```

The agent validates the local Appium/ADB stack before pairing. The one-time
pairing token expires after 10 minutes. The durable runner token is stored using
Windows DPAPI under the current Windows account; it is never written in
plaintext by this agent. Do not share the pairing command or copy the DPAPI file
to another machine. Revoke a runner from the Test Execution page before
retiring the laptop.

Start the outbound worker in a terminal:

```powershell
tools/local_runner/.venv/Scripts/python.exe tools/local_runner/agent.py run
```

To start the installed stack and runner in the background:

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_runner/start.ps1
```

Supply `-EmulatorName` with an existing Android virtual device name to start it
when no device is online. The startup script reuses a running Appium server and
runner, keeps Appium on loopback, and writes logs under `tools/local_runner/logs`.

Run a real Android Settings smoke check and save its screenshot and result:

```powershell
tools/local_runner/.venv/Scripts/python.exe tools/local_runner/smoke.py --output outputs/android-smoke
```

Use `tools/local_runner/.venv/Scripts/python.exe tools/local_runner/agent.py run --once` to claim at most one run,
or `tools/local_runner/.venv/Scripts/python.exe tools/local_runner/agent.py doctor` to diagnose the local stack. The
runner currently supports Android only; iOS requires a separate macOS/XCUITest
runner.

## Safety and boundaries

- A runner is scoped to one QTXpert project; pair one runner per project.
- Only `local_runner` mobile execution plans are leased to this agent.
- APK bytes are streamed to a temporary directory, SHA-256 verified against
  repository metadata, and deleted after the run.
- Only the explicit mobile command language (launch, tap/click, fill,
  assert-text, assert-visible, back) is executed. Unsupported prose is marked
  blocked; it is never converted into actions by the runner.
- Run reports include bounded startup screenshot (5 MB max) and page source
  (2 MB max). The agent logs run IDs and counts, not test input values or tokens.
- Credentials for the AUT are not part of the runner protocol. Keep secrets out
  of test steps; use synthetic data or the app's approved secret references.
- Keep the laptop awake, connected, and Appium/ADB running for queued work.
  Expired job leases can be reclaimed a maximum of three times.

## Backend rollout prerequisite

The API schema migration `0029_local_device_runners` must be applied before
enrollment is enabled. The feature must be deployed to the API and frontend
together. This source branch does not change production by itself.
