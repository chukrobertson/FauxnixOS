param(
  [string]$HostAddress = "100.126.117.60",
  [int]$Port = 4433,
  [string]$Token = "",
  [string]$TokenFile = "",
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

$DataDir = Join-Path $env:LOCALAPPDATA "Fauxnix"
$ProviderScript = Join-Path $PSScriptRoot "faux_pass_provider.py"
$LogDir = Join-Path $DataDir "logs"
$LogPath = Join-Path $LogDir "faux-pass-provider.log"
$ErrPath = Join-Path $LogDir "faux-pass-provider.err.log"
$DefaultTokenFile = Join-Path $DataDir "faux-pass-provider.token"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-TokenFile {
  param(
    [string]$Path,
    [string]$Value
  )
  $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  [System.IO.File]::WriteAllText($Path, $Value, $Utf8NoBom)
}

if (-not $TokenFile) {
  $TokenFile = $DefaultTokenFile
}

if ($Token -and -not (Test-Path -LiteralPath $TokenFile)) {
  Write-TokenFile -Path $TokenFile -Value $Token
}

if (-not (Test-Path -LiteralPath $TokenFile)) {
  $Bytes = [byte[]]::new(32)
  $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $Rng.GetBytes($Bytes)
  } finally {
    $Rng.Dispose()
  }
  $GeneratedToken = [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
  Write-TokenFile -Path $TokenFile -Value $GeneratedToken
}

$Listeners = netstat -ano | Select-String -Pattern "TCP\s+$([regex]::Escape($HostAddress)):$Port\s+.*LISTENING\s+(\d+)"
if ($Listeners) {
  $ListenerPids = @($Listeners | ForEach-Object { [int]$_.Matches[0].Groups[1].Value } | Sort-Object -Unique)
  if (-not $Restart) {
    "Faux-pass Nexus provider already listening on http://$HostAddress`:$Port/faux-pass pid=$($ListenerPids -join ',')"
    exit 0
  }
  foreach ($ListenerPid in $ListenerPids) {
    Stop-Process -Id $ListenerPid -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 500
}

$Arguments = @(
  "-u",
  $ProviderScript,
  "--host",
  $HostAddress,
  "--port",
  [string]$Port,
  "--token-file",
  $TokenFile
)

if ($Token) {
  $Arguments += @("--token", $Token)
}

$Process = Start-Process `
  -FilePath "python" `
  -ArgumentList $Arguments `
  -WorkingDirectory $PSScriptRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $LogPath `
  -RedirectStandardError $ErrPath `
  -PassThru

"Started Faux-pass Nexus provider pid=$($Process.Id) endpoint=http://$HostAddress`:$Port/faux-pass token_file=$TokenFile log=$LogPath err=$ErrPath"
