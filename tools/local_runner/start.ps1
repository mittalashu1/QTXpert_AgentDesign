param(
    [string]$EmulatorName,
    [string]$AppiumEntry,
    [ValidateRange(1536,8192)][int]$EmulatorMemoryMB = 1536,
    [ValidateRange(1,8)][int]$EmulatorCores = 2
)

$ErrorActionPreference = "Stop"
$runnerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runnerPython = Join-Path $runnerDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $runnerPython)) { throw "Run tools/local_runner/setup.ps1 first." }
$sdkRoot = $env:ANDROID_SDK_ROOT
if (-not $sdkRoot) { $sdkRoot = $env:ANDROID_HOME }
if (-not $sdkRoot) { $sdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk" }
$env:ANDROID_SDK_ROOT = $sdkRoot
$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_USER_HOME = Join-Path $env:USERPROFILE ".android"
$env:PATH = "$(Join-Path $sdkRoot 'platform-tools');$env:PATH"
$logDir = Join-Path $runnerDir "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

if (-not $EmulatorName -and (Test-Path -LiteralPath (Join-Path $env:ANDROID_USER_HOME 'avd\QTXpert_Android16.ini'))) { $EmulatorName = 'QTXpert_Android16' }
if ($EmulatorName) {
    $adb = Join-Path $sdkRoot "platform-tools\adb.exe"
    $deviceList = & $adb devices
    if (-not ($deviceList | Where-Object { $_ -match '^\S+\s+device\s*$' })) {
        $emulator = Join-Path $sdkRoot "emulator\emulator.exe"
        $available = & $emulator -list-avds
        if ($available -notcontains $EmulatorName) { throw "The selected emulator does not exist: $EmulatorName" }
        Start-Process -FilePath $emulator -ArgumentList @("-avd", $EmulatorName, "-memory", "$EmulatorMemoryMB", "-cores", "$EmulatorCores", "-no-window", "-no-audio", "-no-boot-anim") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "emulator.out.log") -RedirectStandardError (Join-Path $logDir "emulator.err.log") | Out-Null
        $deviceOnline = $false
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            $deviceList = & $adb devices
            if ($deviceList | Where-Object { $_ -match '^\S+\s+device\s*$' }) { $deviceOnline = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $deviceOnline) { throw "The emulator did not connect within two minutes. Check the emulator logs." }
    }
}

$serverReady = $false
try { $serverReady = (Invoke-RestMethod "http://127.0.0.1:4723/status" -TimeoutSec 5).value.ready } catch {}
if (-not $serverReady) {
    if (-not $AppiumEntry) {
        $installedEntry = Join-Path $env:LOCALAPPDATA "QTXpert\android-runner\node_modules\appium\build\lib\main.js"
        if (Test-Path -LiteralPath $installedEntry) { $AppiumEntry = $installedEntry }
    }
    if (-not $AppiumEntry -or -not (Test-Path -LiteralPath $AppiumEntry)) {
        throw "Specify -AppiumEntry with the Appium main.js path from your installed Appium package."
    }
    $node = (Get-Command node -ErrorAction Stop).Source
    $installedHome = Join-Path $env:LOCALAPPDATA "QTXpert\android-runner\appium-home"
    if (-not $env:APPIUM_HOME -and (Test-Path -LiteralPath $installedHome)) { $env:APPIUM_HOME = $installedHome }
    Start-Process -FilePath $node -ArgumentList @("`"$AppiumEntry`"", "--address", "127.0.0.1", "--port", "4723") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "appium.out.log") -RedirectStandardError (Join-Path $logDir "appium.err.log") | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { $serverReady = (Invoke-RestMethod "http://127.0.0.1:4723/status" -TimeoutSec 2).value.ready } catch {}
        if ($serverReady) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $serverReady) { throw "Appium did not start. Check tools/local_runner/logs." }
}

& $runnerPython (Join-Path $runnerDir "agent.py") doctor
if ($LASTEXITCODE -ne 0) { throw "The device stack needs attention; see the doctor result above." }
$credentials = Join-Path $env:LOCALAPPDATA "QTXpert\local-runner.dpapi"
if (-not (Test-Path -LiteralPath $credentials)) {
    Write-Host "Android and Appium are ready. Pair this laptop from QTXpert Test Execution to start the outbound runner."
    exit 0
}
$agentPath = Join-Path $runnerDir "agent.py"
$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($agentPath) -and $_.CommandLine -match '\brun\b' }
if ($running) {
    Write-Host "The QTXpert runner is already running."
    exit 0
}
$process = Start-Process -FilePath $runnerPython -ArgumentList @("-u", "`"$agentPath`"", "run") -WorkingDirectory $runnerDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "runner.out.log") -RedirectStandardError (Join-Path $logDir "runner.err.log") -PassThru
Write-Host "QTXpert runner started (PID $($process.Id)). Logs: $logDir"
