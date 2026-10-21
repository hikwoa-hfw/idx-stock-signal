# Register Windows Task Scheduler task for IDX Stock Signal Daily Pipeline
# Target schedule: Monday through Friday at 16:30 (Asia/Jakarta exchange local time)

param(
    [string]$TaskName = "IDX_Stock_Signal_Daily_Pipeline",
    [string]$ExecutionTime = "16:30",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$RunnerScript = Join-Path $ScriptDir "run_scheduled_pipeline.ps1"
$VbsRunner = Join-Path $ScriptDir "run_scheduled_pipeline.vbs"

if (-not (Test-Path $RunnerScript)) {
    Write-Error "Scheduled runner script not found at: $RunnerScript"
    exit 1
}

Write-Output "Configuring Windows Task Scheduler for $TaskName..."
Write-Output "Project Root: $ProjectRoot"
Write-Output "Runner Script: $RunnerScript"
Write-Output "Schedule: Mon-Fri at $ExecutionTime"

# Check if task already exists
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask -and -not $Force) {
    Write-Warning "Task '$TaskName' already exists. Use -Force to overwrite."
    exit 0
}

try {
    # Execute silently via wscript.exe so no console popup window appears
    if (Test-Path $VbsRunner) {
        $Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsRunner`"" -WorkingDirectory $ProjectRoot
    } else {
        $ActionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunnerScript`""
        $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArgs -WorkingDirectory $ProjectRoot
    }
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $ExecutionTime
    
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily market-data-to-paper-trading pipeline for IDX Stock Signal" -Force | Out-Null
    Write-Output "SUCCESS: Task '$TaskName' registered successfully via Register-ScheduledTask (Silent Background Execution)."
}
catch {
    Write-Warning "PowerShell Register-ScheduledTask failed ($_.Exception.Message). Falling back to schtasks.exe..."
    if (Test-Path $VbsRunner) {
        $SchtasksCmd = "schtasks.exe /create /tn `"$TaskName`" /tr `"wscript.exe `\`"$VbsRunner`\`"`" /sc weekly /d MON,TUE,WED,THU,FRI /st $ExecutionTime /f"
    } else {
        $ActionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunnerScript`""
        $SchtasksCmd = "schtasks.exe /create /tn `"$TaskName`" /tr `"powershell.exe $ActionArgs`" /sc weekly /d MON,TUE,WED,THU,FRI /st $ExecutionTime /f"
    }
    Invoke-Expression $SchtasksCmd
    if ($LASTEXITCODE -eq 0) {
        Write-Output "SUCCESS: Task '$TaskName' registered successfully via schtasks.exe."
    } else {
        Write-Error "Failed to register task via schtasks.exe."
        exit 1
    }
}

# Verify task existence
Write-Output "Verifying registered task..."
schtasks.exe /query /tn "$TaskName" /fo LIST
