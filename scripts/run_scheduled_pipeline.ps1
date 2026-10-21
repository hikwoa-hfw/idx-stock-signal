# PowerShell wrapper for daily pipeline scheduled execution
# Enforces single-instance execution via lockfile, sets up paths, and persists logs.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location -Path $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment Python executable not found at: $VenvPython"
    exit 1
}

$LogsDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

$LockFile = Join-Path $ProjectRoot "artifacts\pipeline_runs\pipeline.lock"
$LockDir = Split-Path -Parent $LockFile
if (-not (Test-Path $LockDir)) {
    New-Item -ItemType Directory -Path $LockDir -Force | Out-Null
}

# Single instance lock check
if (Test-Path $LockFile) {
    $LockContent = Get-Content $LockFile -Raw -ErrorAction SilentlyContinue
    Write-Warning "Another daily pipeline instance appears to be running (lockfile present: $LockContent). Aborting."
    exit 0
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogsDir "daily_pipeline_$Timestamp.log"

# Create lock
$PIDStr = "$PID - $(Get-Date -Format 'o')"
Set-Content -Path $LockFile -Value $PIDStr

try {
    Write-Output "[$Timestamp] Starting daily pipeline run..." | Tee-Object -FilePath $LogFile
    $PrevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VenvPython -m scripts.run_daily_pipeline @args 2>&1 | Tee-Object -FilePath $LogFile -Append
    $ExitCode = $LASTEXITCODE
    $ErrorActionPreference = $PrevEAP
    Write-Output "[$Timestamp] Pipeline finished with exit code: $ExitCode" | Tee-Object -FilePath $LogFile -Append
    exit $ExitCode
}
finally {
    if (Test-Path $LockFile) {
        Remove-Item -Path $LockFile -Force -ErrorAction SilentlyContinue
    }
}
