param(
    [string]$EmulatorName,
    [string]$AppiumEntry,
    [ValidateRange(1536,8192)][int]$EmulatorMemoryMB = 1536,
    [ValidateRange(1,8)][int]$EmulatorCores = 2,
    [ValidateRange(30,1800)][int]$BootTimeoutSeconds = 900,
    [switch]$UsbDevice,
    [string]$JavaHome
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

$adb = Join-Path $sdkRoot "platform-tools\adb.exe"
$agentOptions = @()
if ($UsbDevice) {
    if ($EmulatorName) { throw "Choose either -UsbDevice or -EmulatorName." }
    $deviceSerial = ((& $adb -d get-serialno) -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $deviceSerial -or $deviceSerial -eq 'unknown') {
        throw "Connect one USB Android phone, unlock it, and allow USB debugging."
    }
    $agentOptions = @('--device-serial', $deviceSerial)
}

if (-not $UsbDevice -and -not $EmulatorName) {
    foreach ($candidate in @('QTXpert_Android14', 'QTXpert_Android16')) {
        if (Test-Path -LiteralPath (Join-Path $env:ANDROID_USER_HOME "avd\$candidate.ini")) { $EmulatorName = $candidate; break }
    }
}
if ($EmulatorName) {
    function Get-AvdDeviceSerial {
        param([string]$AdbPath, [string]$AvdName)
        $deviceList = & $AdbPath devices
        foreach ($line in $deviceList) {
            if ($line -match '^(emulator-\d+)\s+device\b') {
                $serial = $Matches[1]
                $avdResponse = & $AdbPath -s $serial emu avd name 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $reportedName = $avdResponse | Where-Object { $_ -and $_.Trim() -ne 'OK' } | Select-Object -First 1
                    if ($reportedName -and $reportedName.Trim() -eq $AvdName) { return $serial }
                }
            }
        }
        return $null
    }

    $deviceSerial = Get-AvdDeviceSerial -AdbPath $adb -AvdName $EmulatorName
    if (-not $deviceSerial) {
        $emulator = Join-Path $sdkRoot "emulator\emulator.exe"
        $available = & $emulator -list-avds
        if ($available -notcontains $EmulatorName) { throw "The selected emulator does not exist: $EmulatorName" }
        Start-Process -FilePath $emulator -ArgumentList @("-avd", $EmulatorName, "-memory", "$EmulatorMemoryMB", "-cores", "$EmulatorCores", "-no-window", "-no-audio", "-no-boot-anim") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "emulator.out.log") -RedirectStandardError (Join-Path $logDir "emulator.err.log") | Out-Null
    }

    $deviceOnline = $false
    for ($attempt = 0; $attempt -lt $BootTimeoutSeconds; $attempt++) {
        $deviceSerial = Get-AvdDeviceSerial -AdbPath $adb -AvdName $EmulatorName
        if ($deviceSerial) {
            $bootCompleted = & $adb -s $deviceSerial shell getprop sys.boot_completed
            if ($LASTEXITCODE -eq 0 -and ($bootCompleted -join '').Trim() -eq '1') { $deviceOnline = $true; break }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $deviceOnline) { throw "Android emulator '$EmulatorName' did not complete boot within $BootTimeoutSeconds seconds. Check emulator logs, free disk space and available memory." }
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
    $portAlreadyListening = $false
    $tcpClient = $null
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connect = $tcpClient.BeginConnect("127.0.0.1", 4723, $null, $null)
        if ($connect.AsyncWaitHandle.WaitOne(500)) {
            $tcpClient.EndConnect($connect)
            $portAlreadyListening = $true
        }
    } catch {} finally { if ($tcpClient) { $tcpClient.Close() } }
    if (-not $portAlreadyListening) {
        if (-not $JavaHome) {
            $javaCandidates = @($env:JAVA_HOME)
            $javaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
            if ($javaCommand) {
                $javaCandidates += Split-Path -Parent (Split-Path -Parent $javaCommand.Source)
            }
            if ($env:ProgramFiles) {
                $javaCandidates += Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'
                $javaCandidates += @(Get-ChildItem -LiteralPath (Join-Path $env:ProgramFiles 'Java') -Directory -Filter 'jdk-*' -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -ExpandProperty FullName)
            }
            $JavaHome = $javaCandidates | Where-Object {
                $_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\java.exe') -PathType Leaf)
            } | Select-Object -First 1
        }
        if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\java.exe') -PathType Leaf)) {
            throw "Appium needs Java to install and verify Android APKs. Specify -JavaHome with the installed JDK directory."
        }
        $env:JAVA_HOME = (Resolve-Path -LiteralPath $JavaHome).Path
        $env:PATH = "$(Join-Path $env:JAVA_HOME 'bin');$env:PATH"
        Start-Process -FilePath $node -ArgumentList @("`"$AppiumEntry`"", "--address", "127.0.0.1", "--port", "4723") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "appium.out.log") -RedirectStandardError (Join-Path $logDir "appium.err.log") | Out-Null
    }
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        try { $serverReady = (Invoke-RestMethod "http://127.0.0.1:4723/status" -TimeoutSec 2).value.ready } catch {}
        if ($serverReady) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $serverReady) { throw "Appium did not start. Check tools/local_runner/logs." }
}

$agentPath = Join-Path $runnerDir "agent.py"
& $runnerPython $agentPath @agentOptions doctor
if ($LASTEXITCODE -ne 0) { throw "The device stack needs attention; see the doctor result above." }
$credentials = Join-Path $env:LOCALAPPDATA "QTXpert\local-runner.dpapi"
if (-not (Test-Path -LiteralPath $credentials)) {
    Write-Host "Android and Appium are ready. Pair this laptop from QTXpert Test Execution to start the outbound runner."
    exit 0
}
$running = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($agentPath) -and $_.CommandLine -match '\brun\b' })
if ($running) {
    if ($UsbDevice) {
        $serialPattern = '(?:^|\s)--device-serial\s+"?{0}"?(?=\s|$)' -f [regex]::Escape($deviceSerial)
        if ($running | Where-Object { $_.CommandLine -cnotmatch $serialPattern }) {
            throw "A runner is already running with a different device selection. Stop it before starting USB mode."
        }
    }
    Write-Host "The QTXpert runner is already running."
    exit 0
}
$runnerArgs = @("-u", "`"$agentPath`"")
if ($UsbDevice) { $runnerArgs += @('--device-serial', "`"$deviceSerial`"") }
$runnerArgs += 'run'
$process = Start-Process -FilePath $runnerPython -ArgumentList $runnerArgs -WorkingDirectory $runnerDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "runner.out.log") -RedirectStandardError (Join-Path $logDir "runner.err.log") -PassThru
Write-Host "QTXpert runner started (PID $($process.Id)). Logs: $logDir"
