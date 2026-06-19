# ── SWAY CONFIG SNIPPET ────────────────────────────────────────────────
# Replace the fauxshell-host lines in /etc/sway/config with these.
# The workspace canvas becomes the primary desktop surface.

# ── Desktop canvas (replaces exec fauxshell-host) ────────────────────
# This is the infinite node-graph canvas — the login desktop.
exec fauxnix-workspace

# Launcher overlay (replaces exec fauxshell-host --launcher)
# Toggled by F12. Runs as a separate top-layer process.
exec fauxnix-workspace --launcher

# ── Window rules for the workspace ────────────────────────────────────
# Desktop canvas: fullscreen, no border, bottom layer, on workspace 1
for_window [app_id="fauxnix-workspace"] fullscreen enable, border none

# Launcher: floating, sticky, top layer, no border
for_window [app_id="fauxnix-launcher"] floating enable, sticky enable, border none

# ── Keybindings ──────────────────────────────────────────────────────
# F12: toggle launcher visibility
bindsym F12 exec pkill -f "fauxnix-workspace --launcher" || fauxnix-workspace --launcher

# Trackpad gestures → shell events (keep existing)
bindgesture swipe:3:right exec fauxshellctl nav back
bindgesture swipe:3:left exec fauxshellctl nav forward
bindgesture swipe:3:down kill

# ── Auto-start services ──────────────────────────────────────────────
exec fauxd
exec fauxnix-power start

# ── Workspace assignments ────────────────────────────────────────────
# Apps launched from workspace nodes go to their own workspaces
assign [app_id="firefox"] "3:Web"
assign [app_id="foot"] "4:Terminal"

# Remove old fauxshell-host exec lines
# Remove old fauxshell-host --launcher exec lines
