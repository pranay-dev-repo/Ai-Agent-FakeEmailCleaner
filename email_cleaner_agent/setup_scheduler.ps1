# Run this script as Administrator to register the daily Task Scheduler job.
# The task will run daily_agent.py every day at 7:00 AM.

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerPath = Join-Path $ScriptDir "run_daily_agent.ps1"

if (-not (Test-Path $RunnerPath)) {
    Write-Error "run_daily_agent.ps1 not found at $RunnerPath"
    exit 1
}

# Prompt for API key to store as a system environment variable
$apiKey = Read-Host "Enter your Groq API key (stored as system env var GROQ_API_KEY; press Enter to skip)"
if ($apiKey) {
    [System.Environment]::SetEnvironmentVariable("GROQ_API_KEY", $apiKey, "Machine")
    Write-Host "GROQ_API_KEY saved as a system environment variable."
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$RunnerPath`"" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -Daily -At "7:00AM"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "EmailCleanerDailyAgent" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily Gmail domain scanner and AI-powered cleaner" `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "Task 'EmailCleanerDailyAgent' registered successfully."
Write-Host "It will run daily at 7:00 AM."
Write-Host ""
Write-Host "To run it manually right now:"
Write-Host "  Start-ScheduledTask -TaskName 'EmailCleanerDailyAgent'"
Write-Host ""
Write-Host "To remove the task later:"
Write-Host "  Unregister-ScheduledTask -TaskName 'EmailCleanerDailyAgent' -Confirm:`$false"
