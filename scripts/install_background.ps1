param(
  [string]$TaskName = 'API Radar Dashboard',
  [int]$DelaySeconds = 20
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $PSScriptRoot 'open_radar.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $launcher)) { throw "Launcher not found: $launcher" }
$action = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -RandomDelay (New-TimeSpan -Seconds $DelaySeconds)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Description 'Start API Radar locally after sign-in when AC power is connected, then open the dashboard' -Force | Out-Null
Write-Output "Installed background dashboard task '$TaskName' with a $DelaySeconds-second logon delay."
