' Fauxnix Nexus — silent boot launcher (no terminal flash)
' Launches Host GUI + Faux-pass provider via WScript.Shell.Run with hidden window.

Dim shell
Set shell = CreateObject("WScript.Shell")

' Launch Nexus Host GUI (pythonw.exe — already windowless)
shell.Run """C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe"" ""E:\Fauxnix\nexus-host\nexus_host.py""", 0, False

' Launch Faux-pass provider (powershell — hidden via Run flag 0)
shell.Run """C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"" -WindowStyle Hidden -ExecutionPolicy Bypass -File ""E:\Fauxnix\remote-nixos\faux-pass\provider\start-nexus-provider.ps1"" -Restart", 0, False
