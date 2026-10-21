# Unregister Windows Task Scheduler task for IDX Stock Signal Daily Pipeline

param(
    [string]$TaskName = "IDX_Stock_Signal_Daily_Pipeline"
)

$ErrorActionPreference = "Stop"

Write-Output "Removing scheduled task '$TaskName'..."
schtasks.exe /delete /tn "$TaskName" /f

if ($LASTEXITCODE -eq 0) {
    Write-Output "SUCCESS: Task '$TaskName' was successfully removed."
} else {
    Write-Warning "Task '$TaskName' could not be removed or did not exist."
}
