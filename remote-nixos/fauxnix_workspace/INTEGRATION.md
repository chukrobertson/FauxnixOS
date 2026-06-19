# ── Add to /etc/nixos/configuration.nix ──────────────────────────────
# Inside the big environment.systemPackages list (or as a new entry):

# Add PyQt6 to system packages:
#   pkgs.python3Packages.pyqt6
#   pkgs.python3Packages.pyqt6-webengine

# Add workspace launcher to /etc/fauxnix/:
# (Add this in the activationScripts or fileSystems section where
#  other scripts like fauxnix-git.sh are copied)

# Copy workspace files:
#   cp -r ${./fauxnix_workspace} /home/chvk/Fauxnix/remote-nixos/fauxnix_workspace

# Add faux-pass registry entry for the workspace:
# {
#   "id": "workspace",
#   "name": "Workspace Canvas",
#   "action": ["fauxnix-workspace"]
# }

# Quick test from SSH (no display):
#   nix-shell -p python3Packages.pyqt6 python3Packages.pyqt6-webengine \
#     --run "QT_QPA_PLATFORM=offscreen python3 -c 'from PyQt6.QtWidgets import QApplication; app=QApplication([]); print(\"QApp OK\")'"

# Run on Sway desktop:
#   cd ~/Fauxnix/remote-nixos
#   nix-shell -p python3Packages.pyqt6 python3Packages.pyqt6-webengine \
#     --run "QT_QPA_PLATFORM=wayland python3 -m fauxnix_workspace"
