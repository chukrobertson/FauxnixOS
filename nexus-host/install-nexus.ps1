#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Installs Fauxnix Nexus components on Windows.
.DESCRIPTION
    Sets up the Nexus Host GUI and Faux-pass provider to run at boot,
    checks Python dependencies, and creates required directories.
.PARAMETER NoPythonCheck
    Skip Python dependency validation.
.PARAMETER NoProvider
    Skip Faux-pass provider startup setup.
.PARAMETER NoHost
    Skip Nexus Host GUI startup setup.
#>

param(
    [switch]$NoPythonCheck,
    [switch]$NoProvider,
    [switch]$NoHost
)

$ErrorActionPreference = "Stop"

# ── paths ──────────────────────────────────────────────────────────
$RepoRoot    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$NexusHost   = Join-Path $PSScriptRoot "nexus_host.py"
$ProviderDir = Join-Path $RepoRoot "remote-nixos" "faux-pass" "provider"
$ProviderPs1 = Join-Path $ProviderDir "start-nexus-provider.ps1"
$ProviderCmd = Join-Path $ProviderDir "run-nexus-provider.cmd"
$DataDir     = Join-Path $env:LOCALAPPDATA "Fauxnix"
$LogDir      = Join-Path $DataDir "logs"
$StartupDir  = [Environment]::GetFolderPath("Startup")
$RunKey      = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

# ── helpers ────────────────────────────────────────────────────────
function Write-Step($msg) {
    Write-Host "  → $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "  ✔ $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "  ⚠ $msg" -ForegroundColor Yellow
}

# ── header ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      Fauxnix Nexus — Windows Installer       ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Directories ────────────────────────────────────────────────
Write-Step "Creating data and log directories..."
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir  | Out-Null
Write-Ok "$DataDir"
Write-Ok "$LogDir"

# ── 2. Python dependencies ────────────────────────────────────────
if (-not $NoPythonCheck) {
    Write-Step "Checking Python and dependencies..."
    $python = (Get-Command "python" -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        $python = (Get-Command "python3" -ErrorAction SilentlyContinue).Source
    }
    if (-not $python) {
        Write-Warn "Python not found on PATH. Install Python 3.12+ from https://www.python.org/"
        Write-Warn "  Make sure 'Add Python to PATH' is checked during installation."
    } else {
        Write-Ok "Python: $python"
        # Check PyQt6
        $has_pyqt = & $python -c "import PyQt6; print(PyQt6.QtCore.PYQT_VERSION_STR)" 2>$null
        if (-not $has_pyqt) {
            Write-Step "Installing PyQt6..."
            & $python -m pip install PyQt6 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "PyQt6 installed"
            } else {
                Write-Warn "PyQt6 install failed. Run: pip install PyQt6"
            }
        } else {
            Write-Ok "PyQt6 $has_pyqt"
        }
    }
}

# ── 3. Faux-pass provider startup ─────────────────────────────────
if (-not $NoProvider) {
    Write-Step "Setting up Faux-pass provider at boot..."
    $providerTarget = Join-Path $StartupDir "Fauxnix Faux-pass Nexus Provider.cmd"

    if (Test-Path -LiteralPath $ProviderCmd) {
        $content = "@echo off`r`ncall `"$ProviderCmd`"`r`n"
        $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($providerTarget, $content, $Utf8NoBom)
        Write-Ok "Startup shortcut: $providerTarget"

        # Start it now if not already running
        $listener = netstat -ano | Select-String -Pattern "TCP\s+100\.126\.117\.60:4433\s+.*LISTENING"
        if (-not $listener) {
            Write-Step "Starting Faux-pass provider..."
            try {
                & $ProviderPs1 -Restart 2>&1 | Out-Null
                Write-Ok "Faux-pass provider started"
            } catch {
                Write-Warn "Could not start provider: $_"
                Write-Warn "  Run manually: $ProviderPs1"
            }
        } else {
            Write-Ok "Faux-pass provider already running"
        }
    } else {
        Write-Warn "Provider script not found at: $ProviderCmd"
        Write-Warn "  The faux-pass provider may not be available in this checkout."
    }
}

# ── 4. Nexus Host GUI startup ─────────────────────────────────────
if (-not $NoHost) {
    Write-Step "Setting up Nexus Host GUI at boot..."

    $hostScript = $PSScriptRoot -replace '\\', '\\'
    $hostScript = Join-Path $hostScript "nexus_host.py"
    $pythonExe = "pythonw.exe"
    $cmdLine = "$pythonExe `"$hostScript`""

    # Write to Registry Run key
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $regName = "Fauxnix Nexus Host"
    try {
        Set-ItemProperty -Path $regPath -Name $regName -Value $cmdLine
        Write-Ok "Registry Run key: $regName"
    } catch {
        Write-Warn "Could not write Registry Run key: $_"
        Write-Warn "  Falling back to Startup folder shortcut."

        $hostTarget = Join-Path $StartupDir "Fauxnix Nexus Host.cmd"
        $content = "@echo off`r`nstart /b $cmdLine`r`n"
        $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($hostTarget, $content, $Utf8NoBom)
        Write-Ok "Startup shortcut: $hostTarget"
    }

    # Launch now
    $nexusProc = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "nexus_host" }
    if (-not $nexusProc) {
        Write-Step "Launching Nexus Host GUI..."
        try {
            Start-Process -FilePath "pythonw.exe" -ArgumentList "`"$hostScript`"" -WindowStyle Hidden
            Write-Ok "Nexus Host GUI launched"
        } catch {
            Write-Warn "Could not launch Nexus Host: $_"
            Write-Warn "  Run manually: pythonw `"$hostScript`""
        }
    } else {
        Write-Ok "Nexus Host GUI already running"
    }
}

# ── summary ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║         Installation complete!               ║" -ForegroundColor Green
Write-Host "╚═══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Nexus Host GUI : $PSScriptRoot\nexus_host.py" -ForegroundColor White
Write-Host "  Faux-pass API  : http://100.126.117.60:4433/faux-pass" -ForegroundColor White
Write-Host "  Logs           : $LogDir" -ForegroundColor White
Write-Host ""
Write-Host "  Use the Nexus Host UI (Status tab → Startup) to toggle boot behavior." -ForegroundColor Cyan
Write-Host ""
