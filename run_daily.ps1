# Data update, run by Windows Task Scheduler ("NBA Fantasy Daily Update"): every 3 hours from 09:00, when Roi logs on,
# and when the computer wakes from sleep. It pulls the 2026-27 game logs, schedule, rosters and injuries, rebuilds the
# website and pushes it to GitHub Pages. Injuries are also refreshed in the cloud (.github/workflows/injuries.yml).
# Every step is logged to logs\daily_update.log as it starts, so a run that stops shows where.

Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:GIT_TERMINAL_PROMPT = "0"   # never wait for a password prompt in the hidden window: fail and retry instead
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$log = Join-Path $PSScriptRoot "logs\daily_update.log"

function Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $log -Append -Encoding utf8
}
function Run($label, $exe, [string[]]$arguments) {
    Log "$label..."
    $output = & $exe @arguments 2>&1 | Out-String
    if ($output.Trim()) { $output.TrimEnd() | Out-File -FilePath $log -Append -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "$label failed (exit $LASTEXITCODE)"; exit 1 }
}

# Keep the log short: the last ~400 lines are enough to see what happened
if ((Test-Path $log) -and ((Get-Content $log).Count -gt 600)) { Get-Content $log -Tail 400 | Set-Content $log -Encoding utf8 }

Log "start"
# The cloud refreshes injuries during the day; start from its latest commit
Run "sync" "git" @("pull", "-q", "--rebase", "--autostash")
Run "pull data" "python" @("daily_update.py")
Run "build" "python" @("build_dashboard.py")

& git add -A -- nba_2026_27 docs draft_dashboard.html
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Log "no new data"
} else {
    Run "commit" "git" @("commit", "-q", "-m", "Daily data update $(Get-Date -Format 'yyyy-MM-dd HH:mm')")
    Run "sync" "git" @("pull", "-q", "--rebase", "--autostash")
    Run "push" "git" @("push", "-q")
    Log "pushed"
}
Log "done"
