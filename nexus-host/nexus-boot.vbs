' Fauxnix Nexus - silent boot launcher (zero terminal flash)
' Uses pythonw.exe for both processes - pythonw creates no console window.

Dim shell
Set shell = CreateObject("WScript.Shell")

' Launch Nexus Host GUI (pythonw.exe - no console)
shell.Run """C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe"" ""E:\Fauxnix\nexus-host\nexus_host.py""", 0, False

' Launch Faux-pass provider (pythonw.exe - no console, no powershell flash)
shell.Run """C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe"" ""E:\Fauxnix\remote-nixos\faux-pass\provider\faux_pass_provider.py"" --host 0.0.0.0 --port 4433", 0, False
