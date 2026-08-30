param(
  [string]$Name = 'API Radar 驾驶舱',
  [string]$Hotkey = 'CTRL+ALT+R',
  [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $PSScriptRoot 'open_radar.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`""
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Open the local API Radar decision dashboard'
$shortcut.Hotkey = $Hotkey
$shortcut.Save()

Write-Output "Installed desktop shortcut: $shortcutPath"
Write-Output "Global shortcut: $Hotkey"
if ($StartNow) {
  & $launcher
}
