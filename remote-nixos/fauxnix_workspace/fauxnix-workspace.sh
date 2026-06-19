#!/usr/bin/env bash
# Fauxnix Workspace launcher
# Drop into /etc/fauxnix/ or your PATH

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_SRC="$HOME/Fauxnix/remote-nixos"

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_WAYLAND_DISABLE_WINDOWDECORATION=1

PYTHONPATH="$WORKSPACE_SRC:$PYTHONPATH"

# If PyQt6 isn't in system Python, use nix-shell
if python3 -c "import PyQt6" 2>/dev/null; then
    exec python3 -m fauxnix_workspace "$@"
else
    exec nix-shell -p python3Packages.pyqt6 python3Packages.pyqt6-webengine \
        --run "PYTHONPATH=$PYTHONPATH python3 -m fauxnix_workspace"
fi
