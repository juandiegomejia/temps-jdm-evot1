# setup_scheduler.ps1 — Register Windows Task Scheduler tasks for temps-jdm-evot1
# Run once in PowerShell (no admin needed — tasks run as current user):
#   cd "C:\Users\Juan Diego\Dropbox\Python for data analysys\temps-jdm-evot1"
#   .\setup_scheduler.ps1

$RepoDir = "$env:USERPROFILE\Dropbox\Python for data analysys\temps-jdm-evot1"
$Python  = "$env:USERPROFILE\Dropbox\Python for data analysys\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $Python) {
        Write-Error "Python not found. Edit `$Python in this script."
        exit 1
    }
}

Write-Host "Using Python: $Python"
Write-Host "Repo dir:     $RepoDir"

$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew

# ── Task 0: LibreHardwareMonitor — start at logon ───────────────────────────
$LhmExe      = "$env:USERPROFILE\LibreHardwareMonitor\LibreHardwareMonitor.exe"
$LhmAction   = New-ScheduledTaskAction -Execute $LhmExe
$LhmTrigger  = New-ScheduledTaskTrigger -AtLogOn
$LhmSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName   "LibreHardwareMonitor-JDM" `
    -Action     $LhmAction `
    -Trigger    $LhmTrigger `
    -Settings   $LhmSettings `
    -Description "Start LibreHardwareMonitor at logon (temps-jdm-evot1)" `
    -Force

# ── Task 1: collect.py — every hour ─────────────────────────────────────────
$CollectAction  = New-ScheduledTaskAction -Execute $Python -Argument "`"$RepoDir\collect.py`"" -WorkingDirectory $RepoDir
$CollectTrigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At (Get-Date)

Register-ScheduledTask `
    -TaskName   "TempCollect-JDM" `
    -Action     $CollectAction `
    -Trigger    $CollectTrigger `
    -Settings   $Settings `
    -Description "Hourly hardware temperature collection (temps-jdm-evot1)" `
    -Force

# ── Task 2: report.py — daily at 23:55 ──────────────────────────────────────
$ReportAction  = New-ScheduledTaskAction -Execute $Python -Argument "`"$RepoDir\report.py`"" -WorkingDirectory $RepoDir
$ReportTrigger = New-ScheduledTaskTrigger -Daily -At "23:55"

Register-ScheduledTask `
    -TaskName   "TempReport-JDM" `
    -Action     $ReportAction `
    -Trigger    $ReportTrigger `
    -Settings   $Settings `
    -Description "Daily hardware temperature HTML report (temps-jdm-evot1)" `
    -Force

# ── Task 3: git push logs+reports — daily at 23:58 ──────────────────────────
$PushScript = "$RepoDir\push_logs.ps1"

@"
Set-Location "$RepoDir"
git add logs/ reports/ alerts.log 2>&1
if ((git diff --cached --name-only) -ne '') {
    git commit -m "logs: daily temp data `$(Get-Date -Format 'yyyy-MM-dd')"
    git push
}
"@ | Set-Content -Path $PushScript -Encoding UTF8

$PushAction  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$PushScript`"" -WorkingDirectory $RepoDir
$PushTrigger = New-ScheduledTaskTrigger -Daily -At "23:58"

Register-ScheduledTask `
    -TaskName   "TempPush-JDM" `
    -Action     $PushAction `
    -Trigger    $PushTrigger `
    -Settings   $Settings `
    -Description "Daily git push of temperature logs and reports" `
    -Force

Write-Host ""
Write-Host "Tasks registered:" -ForegroundColor Green
Write-Host "  LibreHardwareMonitor-JDM — at logon"
Write-Host "  TempCollect-JDM          — every hour"
Write-Host "  TempReport-JDM           — daily 23:55"
Write-Host "  TempPush-JDM             — daily 23:58"
