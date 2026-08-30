param(
  [switch]$Refresh,
  [switch]$IgnorePowerCheck
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$dashboard = Join-Path $root 'dashboard'
$dataDirectory = Join-Path $root 'data'
$apiUrl = 'http://127.0.0.1:8000'
$dashboardUrl = 'http://127.0.0.1:5173'

function Test-ACPower {
  <#
    Return $current AC power state without blocking devices that do not expose
    a battery (for example, desktop PCs).  SystemInformation is the most
    reliable source on Windows; Win32_Battery is used as a fallback.
  #>
  try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $lineStatus = [System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus.ToString()
    if ($lineStatus -eq 'Online') { return $true }
    if ($lineStatus -eq 'Offline') { return $false }
  } catch {
    # Continue with the CIM fallback below.
  }

  try {
    $batteries = @(Get-CimInstance -ClassName Win32_Battery -ErrorAction Stop)
    if ($batteries.Count -eq 0) { return $true }
    $charging = @($batteries | Where-Object {
      # 2, 6-11 are the charging states documented by Win32_Battery.
      $_.BatteryStatus -in @(2, 6, 7, 8, 9, 10, 11)
    })
    if ($charging.Count -gt 0) { return $true }

    # A fully charged battery (3) does not always report whether the adapter
    # is connected, so treat it as unknown and allow startup.
    return $true
  } catch {
    # If power cannot be detected, fail open so a desktop or restricted
    # account is not permanently prevented from using API Radar.
    return $true
  }
}

if (-not $IgnorePowerCheck -and -not (Test-ACPower)) {
  Write-Output 'AC power is not connected; API Radar startup skipped (no window opened).'
  exit 0
}

if (-not (Test-Path -LiteralPath $python)) {
  throw "Project interpreter not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $dashboard 'node_modules'))) {
  throw 'Dashboard dependencies are missing. Run: cd dashboard; npm install'
}

New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null

function Test-LocalPort([int]$Port) {
  $client = [System.Net.Sockets.TcpClient]::new()
  try {
    $connect = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
    if (-not $connect.AsyncWaitHandle.WaitOne(350)) { return $false }
    $client.EndConnect($connect)
    return $true
  } catch {
    return $false
  } finally {
    $client.Dispose()
  }
}

function Wait-LocalPort([int]$Port, [string]$Name) {
  foreach ($attempt in 1..60) {
    if (Test-LocalPort $Port) { return }
    Start-Sleep -Milliseconds 500
  }
  throw "$Name did not start on port $Port. Check data\api-radar-*.log."
}

if (-not (Test-LocalPort 8000)) {
  Start-Process -FilePath $python -ArgumentList @(
    '-m', 'uvicorn', 'api_radar.app:app', '--host', '127.0.0.1', '--port', '8000'
  ) -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $dataDirectory 'api-radar-api.log') `
    -RedirectStandardError (Join-Path $dataDirectory 'api-radar-api-error.log')
  Wait-LocalPort 8000 'API Radar API'
}

if (-not (Test-LocalPort 5173)) {
  $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
  Start-Process -FilePath $npm -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1') `
    -WorkingDirectory $dashboard -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $dataDirectory 'api-radar-dashboard.log') `
    -RedirectStandardError (Join-Path $dataDirectory 'api-radar-dashboard-error.log')
  Wait-LocalPort 5173 'API Radar dashboard'
}

if ($Refresh) {
  Invoke-WebRequest -UseBasicParsing -Uri "$apiUrl/intelligence/scans" -Method Post | Out-Null
}

$edgeCandidates = @(
  (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
  (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
  (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
)
$edge = $edgeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if ($edge) {
  Start-Process -FilePath $edge -ArgumentList @("--app=$dashboardUrl", '--window-size=1440,920')
} else {
  Start-Process -FilePath $dashboardUrl
}

Write-Output "Opened API Radar at $dashboardUrl"
