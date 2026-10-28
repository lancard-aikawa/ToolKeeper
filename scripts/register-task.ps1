# Register the "ToolKeeper check" task in Task Scheduler (docs/design.md section 5).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1                     Mondays at 9:00 (a missed run starts when available)
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Day Friday -At 13:30
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Data D:\tk          data folder (default: data_dir in the config)
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister         remove the task
#
# The task only runs "check". It never installs anything: updates run only when a person asks
# (the GUI or "toolkeeper update"), see docs/design.md section 4.
#
# Keep this file ASCII only. Windows PowerShell 5.1 reads a file without BOM as the ANSI code page
# (cp932 on Japanese Windows), so non-ASCII text breaks the parser. pwsh (7) is not always installed.
#
# The task runs scripts\toolkeeper-launch.py with a base interpreter's pythonw.exe found by
# scripts\find-pythonw.ps1 (Python 3.11 or later; no .venv needed), so no console window opens.
# (.venv\Scripts\pythonw.exe made by uv 0.11 is a console launcher and opens one.) Check the result in <data>\last-run.log and the task's
# "Last Run Result": 0 = done, 1 = ToolKeeper bug, 2 = usage, 3 = already running, 4 = some sources could not be checked.
param(
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$Day = "Monday",
    [string]$At = "09:00",
    [string]$Data = "",
    [string]$Name = "ToolKeeper check",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Write-Host "Removed: $Name"
    return
}

$repo = Split-Path -Parent $PSScriptRoot
# A base interpreter's pythonw.exe (no .venv needed). find-pythonw.ps1 prints the reason when none is found.
$pythonw = & (Join-Path $PSScriptRoot "find-pythonw.ps1")
if ($LASTEXITCODE -ne 0 -or -not $pythonw) {
    throw "No Python to run the task (see the message above)."
}
$launcher = Join-Path $repo "scripts\toolkeeper-launch.py"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Warning "winget is not on PATH. The task will report it as a failed source."
}

$arguments = "`"$launcher`" --log"
if ($Data) { $arguments += " --data `"$Data`"" }
$arguments += " check"

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $repo
$weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
# Priority 7 = below normal. Run a missed start when available. Skip when there is no network.
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
# Run only while the user is logged on (no stored password), without admin rights.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $Name -Action $action -Trigger $weekly -Settings $settings `
    -Principal $principal -Description "Check which tools on this PC are out of date; installs nothing ($repo)" -Force | Out-Null
Write-Host "Registered: $Name ($Day at $At)"
Write-Host "  $pythonw $arguments"
