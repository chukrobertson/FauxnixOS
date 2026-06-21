@echo off
cd /d "E:\Fauxnix\nexus-host"

:: Launch Host GUI (pythonw.exe - no console)
start /b "" "C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe" "E:\Fauxnix\nexus-host\nexus_host.py"

:: Wait for Tailscale IP then launch provider
:retry
ping -n 1 100.126.117.60 >nul 2>&1
if errorlevel 1 (
    timeout /t 3 /nobreak >nul
    goto retry
)

start /b "" "C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe" "E:\Fauxnix\remote-nixos\faux-pass\provider\faux_pass_provider.py" --host 100.126.117.60 --port 4433
