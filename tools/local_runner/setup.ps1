param(
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

$runnerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $runnerDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $runnerDir "requirements.txt"
$agent = Join-Path $runnerDir "agent.py"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "The supplied PythonPath does not point to a Python executable."
        }
        & $PythonPath -m venv $venvDir
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venvDir
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venvDir
    } else {
        throw "Python 3.10+ is required. Run setup with -PythonPath pointing to an existing Python executable, or install Python for Windows."
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the runner's Python environment." }
}

$pythonVersion = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or [version]$pythonVersion -lt [version]"3.10") {
    throw "Python 3.10+ is required for the local Android runner. Install a supported Python version and recreate tools/local_runner/.venv."
}

& $venvPython -u -m pip install --isolated --disable-pip-version-check --timeout 30 --retries 1 --progress-bar off -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the local runner's isolated Python dependencies. Check network access to PyPI and rerun setup."
}

# Prefer the standard Android SDK location and make the device tools available
# to both this setup check and the runner process launched from this shell.
$userHome = $env:USERPROFILE
if (-not $userHome) { $userHome = [Environment]::GetFolderPath("UserProfile") }
if ($userHome) {
    if (-not $env:ANDROID_USER_HOME) { $env:ANDROID_USER_HOME = Join-Path $userHome ".android" }
    if (-not $env:ANDROID_SDK_HOME) { $env:ANDROID_SDK_HOME = $userHome }
    if (-not $env:ANDROID_AVD_HOME) { $env:ANDROID_AVD_HOME = Join-Path $env:ANDROID_USER_HOME "avd" }
}
$sdkRoot = $env:ANDROID_SDK_ROOT
if (-not $sdkRoot) { $sdkRoot = $env:ANDROID_HOME }
if (-not $sdkRoot -and $env:LOCALAPPDATA) {
    $defaultSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path -LiteralPath $defaultSdk) { $sdkRoot = $defaultSdk }
}
if ($sdkRoot) {
    $env:ANDROID_SDK_ROOT = $sdkRoot
    $env:ANDROID_HOME = $sdkRoot
    $platformTools = Join-Path $sdkRoot "platform-tools"
    if (Test-Path -LiteralPath $platformTools) { $env:PATH = "$platformTools;$env:PATH" }
}

& $venvPython $agent doctor
if ($LASTEXITCODE -ne 0) {
    throw "Local setup check failed. Confirm Appium is listening on 127.0.0.1:4723 and one Android device/emulator is online in ADB. The doctor output above lists the missing component."
}
