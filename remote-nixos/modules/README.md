# Fauxnix Nix Modules

Keep `configuration.nix` small. Put behavior in the module that owns it.

- `local-packages.nix`: package and script definitions shared through the
  `fauxnix` module argument.
- `base-system.nix`: host basics such as boot, locale, user, audio, printing,
  sudo, browser, and SSH.
- `networking.nix`: Tailscale, NetworkManager, firewall trust, and Wi-Fi
  stability.
- `desktop-wayfire.nix`: SDDM, Wayfire default session, portals, and X keyboard
  layout.
- `agent-runtime.nix`: Ollama, Fennix/Fauxdex runtime files, Faux-pass registry,
  and activation-installed knowledgebase docs.
- `archivist-web.nix`: Archivist FastAPI/browser UI service on port 8776,
  runtime data path, archive root, and firewall access.
- `node-desktop.nix`: browser desktop web service on port 8765, LAN firewall
  access, and kiosk-friendly environment.
- `smb-shares.nix`: Tailscale-bound Samba shares for archive access from
  trusted tailnet devices.
- `system-packages.nix`: system package list and simple command wrappers.

When a change updates agent guidance, update `remote-nixos/docs/knowledge/` and
let activation install it into `/home/chvk/Fauxnix/Knowledge`.
