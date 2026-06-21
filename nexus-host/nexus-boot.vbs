' Fauxnix Nexus - zero-flash boot launcher
' Uses WScript.Shell.Run with 0=hidden window (same pattern as Membrie)

Dim shell
Set shell = CreateObject("WScript.Shell")

' Nexus Host GUI
shell.Run "C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe E:\Fauxnix\nexus-host\nexus_host.py", 0, False

' Faux-pass provider
shell.Run "C:\Users\chukr\AppData\Local\Programs\Python\Python313\pythonw.exe E:\Fauxnix\remote-nixos\faux-pass\provider\faux_pass_provider.py --host 0.0.0.0 --port 4433", 0, False
