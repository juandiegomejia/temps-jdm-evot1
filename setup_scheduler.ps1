# setup_scheduler.ps1 — Register Windows Task Scheduler tasks for temps-jdm-evot1
# Run this ONCE as Administrator in PowerShell:
#   Right-click PowerShell → "Run as administrator"
#   cd "C:\Users\juan_\Dropbox\Python for data analysys\temps-jdm-evot1"
#   .\setup_scheduler.ps1

$RepoDir   = "C:\Users\juan_\Dropbox\Python for data analysys\temps-jdm-evot1"
$Python    = "C:\Users\juan_\Dropbox\Python for data analysys\.venv\Scripts\python.exe"

# ── Fallback to system Python if venv not found ──────────────────────────────
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $Python) {
        Write-Error "Python not found. Edit `$Python in this script."
        exit 1
    }
}

Write-Host "Using Python: $Python"
Write-Host "Repo dir:     $RepoDir"

# ── Task 0: LibreHardwareMonitor — start at logon, run as admin ─────────────
$LhmExe = "C:\Users\juan_\LibreHardwareMonitor\LibreHardwareMonitor.exe"
$LhmAction  = New-ScheduledTaskAction -Execute $LhmExe
$LhmTrigger = New-ScheduledTaskTrigger -AtLogOn
$LhmSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName   "LibreHardwareMonitor-JDM" `
    -Action     $LhmAction `
    -Trigger    $LhmTrigger `
    -Settings   $LhmSettings `
    -RunLevel   Highest `
    -Description "Start LibreHardwareMonitor as admin at logon (required for sensor access)" `
    -Force

# ── Task 1: collect.py — every hour ─────────────────────────────────────────
$CollectAction  = New-ScheduledTaskAction -Execute $Python -Argument "$RepoDir\collect.py" -WorkingDirectory $RepoDir
$CollectTrigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At (Get-Date)
$Settings       = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName   "TempCollect-JDM" `
    -Action     $CollectAction `
    -Trigger    $CollectTrigger `
    -Settings   $Settings `
    -RunLevel   Highest `
    -Description "Hourly hardware temperature collection (temps-jdm-evot1)" `
    -Force

# ── Task 2: report.py — daily at 23:55 ──────────────────────────────────────
$ReportAction  = New-ScheduledTaskAction -Execute $Python -Argument "$RepoDir\report.py" -WorkingDirectory $RepoDir
$ReportTrigger = New-ScheduledTaskTrigger -Daily -At "23:55"

Register-ScheduledTask `
    -TaskName   "TempReport-JDM" `
    -Action     $ReportAction `
    -Trigger    $ReportTrigger `
    -Settings   $Settings `
    -RunLevel   Highest `
    -Description "Daily hardware temperature HTML report (temps-jdm-evot1)" `
    -Force

# ── Task 3: git push logs+reports — daily at 23:58 ──────────────────────────
$GitExe    = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
$PushScript = "$RepoDir\push_logs.ps1"

$PushContent = @"
Set-Location "$RepoDir"
git add logs/ reports/ alerts.log 2>&1
git diff --cached --quiet
if (`$LASTEXITCODE -ne 0) {
    git commit -m "chore: daily log and report `$(Get-Date -Format 'yyyy-MM-dd')"
    git push
}
"@
Set-Content -Path $PushScript -Value $PushContent

$PushAction  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -File `"$PushScript`"" -WorkingDirectory $RepoDir
$PushTrigger = New-ScheduledTaskTrigger -Daily -At "23:58"

Register-ScheduledTask `
    -TaskName   "TempPush-JDM" `
    -Action     $PushAction `
    -Trigger    $PushTrigger `
    -Settings   $Settings `
    -RunLevel   Highest `
    -Description "Daily git push of temperature logs and reports" `
    -Force

Write-Host ""
Write-Host "Tasks registered:" -ForegroundColor Green
Write-Host "  LibreHardwareMonitor-JDM — at logon (as admin, no UAC popup)"
Write-Host "  TempCollect-JDM          — every hour"
Write-Host "  TempReport-JDM           — daily 23:55"
Write-Host "  TempPush-JDM             — daily 23:58"
Write-Host ""
Write-Host "Run a test collection now? (y/n)" -NoNewline
$ans = Read-Host
if ($ans -eq 'y') {
    & $Python "$RepoDir\collect.py"
}
