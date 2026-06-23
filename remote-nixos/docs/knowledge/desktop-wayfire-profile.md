# Desktop Profile: SDDM + Wayfire

Current Fauxnix-Archivist desktop profile:

- Display manager: SDDM
- Session: `wayfire.desktop`
- Window manager/compositor: Wayfire
- Full desktop environment: none
- Primary visible surface: Chromium kiosk at `http://127.0.0.1:8765`
- LAN web UI: `fauxnix-admin-panel` on TCP port 8765
- Workspace UI: `fauxnix-workspace`, PyQt6 forced through XWayland, manual
  until the node import crash is fixed
- Autostart path: SDDM auto-login -> `fauxnix-wayfire-launch` -> Wayfire
  autostart -> `fauxnix-wayfire-startup` -> `fauxd` and Chromium kiosk

Use local evidence before changing compositor state:

- `loginctl list-sessions`
- `systemctl status fauxnix-admin-panel`
- `curl http://127.0.0.1:8765/api/status`
- `pgrep -af 'sddm|wayfire|chromium|fauxnix-workspace|fauxd'`
- `/run/user/1000/fauxnix-wayfire-startup.log`
- `/tmp/wayfire-debug.log`

Do not follow old GNOME/GDM instructions on this branch unless the desktop
branch is intentionally being revived.
