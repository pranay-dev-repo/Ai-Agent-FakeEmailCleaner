# Run this script as Administrator to register the daily Task Scheduler job.
# The task will run email_cleaner.py every day at 8:00 AM.

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe  = (Get-Command python -ErrorAction Stop).Source
$ScriptPath = Join-Path $ScriptDir "email_cleaner.py"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "email_cleaner.py not found at $ScriptPath"
    exit 1
}

# Prompt for API key to store as a system environment variable
$apiKey = Read-Host "Enter your Anthropic API key (stored as system env var ANTHROPIC_API_KEY)"
if ($apiKey) {
    [System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $apiKey, "Machine")
    Write-Host "ANTHROPIC_API_KEY saved as a system environment variable."
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -Daily -At "8:00AM"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "DailyEmailCleaner" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily AI-powered Gmail junk cleaner" `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "Task 'DailyEmailCleaner' registered successfully."
Write-Host "It will run daily at 8:00 AM."
Write-Host ""
Write-Host "To run it manually right now:"
Write-Host "  Start-ScheduledTask -TaskName 'DailyEmailCleaner'"
Write-Host ""
Write-Host "To remove the task later:"
Write-Host "  Unregister-ScheduledTask -TaskName 'DailyEmailCleaner' -Confirm:`$false"
