# Desktop Profile: SDDM + Wayfire

Current Fauxnix-Archivist desktop profile:

- Display manager: SDDM
- Session: `wayfire.desktop`
- Window manager/compositor: Wayfire
- Full desktop environment: none
- Workspace UI: `fauxnix-workspace`, PyQt6 forced through XWayland
- Autostart path: SDDM auto-login -> `fauxnix-wayfire-launch` -> Wayfire
  autostart -> `fauxnix-wayfire-startup` -> `fauxd` and workspace watchdog

Use local evidence before changing compositor state:

- `loginctl list-sessions`
- `pgrep -af 'sddm|wayfire|fauxnix-workspace|fauxd'`
- `/run/user/1000/fauxnix-wayfire-startup.log`
- `/tmp/wayfire-debug.log`

Do not follow old GNOME/GDM instructions on this branch unless the desktop
branch is intentionally being revived.
