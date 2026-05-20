Set-Location "d:\Ai_Projects\AI_Agent"
$logFile = "d:\Ai_Projects\AI_Agent\email_cleaner_agent\scheduler.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $logFile "[$timestamp] Daily agent started"
try {
    & "d:\Ai_Projects\AI_Agent\.venv\Scripts\python.exe" -u "d:\Ai_Projects\AI_Agent\email_cleaner_agent\daily_agent.py"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $logFile "[$timestamp] Daily agent completed (exit $LASTEXITCODE)"
} catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $logFile "[$timestamp] Daily agent ERROR: $_"
}
