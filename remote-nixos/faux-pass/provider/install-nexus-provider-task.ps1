param(
  [string]$TaskName = "Fauxnix Faux-pass Nexus Provider",
  [string]$HostAddress = "100.126.117.60",
  [int]$Port = 4433,
  [string]$TokenFile = ""
)

$ErrorActionPreference = "Stop"

$DataDir = Join-Path $env:LOCALAPPDATA "Fauxnix"
$StartScript = Join-Path $PSScriptRoot "start-nexus-provider.ps1"
if (-not $TokenFile) {
  $TokenFile = Join-Path $DataDir "faux-pass-provider.token"
}

& $StartScript -HostAddress $HostAddress -Port $Port -TokenFile $TokenFile -Restart | Out-Null

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Argument = "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" -HostAddress `"$HostAddress`" -Port $Port -TokenFile `"$TokenFile`""
$PersistenceMode = "scheduled-task"

function Install-StartupRunner {
  $StartupDir = [Environment]::GetFolderPath("Startup")
  $StartupPath = Join-Path $StartupDir "$TaskName.cmd"
  $Runner = Join-Path $PSScriptRoot "run-nexus-provider.cmd"
  $Content = "@echo off`r`ncall `"$Runner`"`r`n"
  [System.IO.File]::WriteAllText($StartupPath, $Content, [System.Text.UTF8Encoding]::new($false))
  return $StartupPath
}

try {
  $Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Argument -WorkingDirectory $PSScriptRoot
  $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel LeastPrivilege
  $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

  Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Starts the Faux-pass Nexus provider for FauxnixOS app launching." `
    -Force | Out-Null
} catch {
  $TaskRun = "`"$PowerShell`" $Argument"
  schtasks /Create /TN $TaskName /SC ONLOGON /TR $TaskRun /F | Out-Null
  if ($LASTEXITCODE -ne 0) {
    $StartupPath = Install-StartupRunner
    $PersistenceMode = "startup-folder:$StartupPath"
  }
}

"Installed $PersistenceMode for $env:USERDOMAIN\$env:USERNAME. Provider endpoint: http://$HostAddress`:$Port/faux-pass"
