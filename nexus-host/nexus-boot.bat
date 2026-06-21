@echo off
cd /d "E:\Fauxnix\nexus-host"

:: Launch compiled Host GUI (true GUI executable - no console)
start /b "" "E:\Fauxnix\nexus-host\dist\FauxnixNexusHost\FauxnixNexusHost.exe"

:: Wait for Tailscale IP then launch compiled provider
:retry
ping -n 1 100.126.117.60 >nul 2>&1
if errorlevel 1 (
    timeout /t 3 /nobreak >nul
    goto retry
)

start /b "" "E:\Fauxnix\nexus-host\dist\FauxnixFauxPass\FauxnixFauxPass.exe" --host 100.126.117.60 --port 4433
