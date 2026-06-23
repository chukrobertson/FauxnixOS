# Nix Module Map

`/etc/nixos/configuration.nix` is intentionally small. It wires together the
hardware scan, shared local package definitions, and focused modules.

Module ownership:

- `configuration.nix`: manifest, imports, shared `fauxnix` module arg, and
  `system.stateVersion`.
- `modules/local-packages.nix`: local derivations, scripts, app wrappers,
  model package pinning, and shared paths.
- `modules/base-system.nix`: bootloader, firmware, graphics, locale, user,
  printing, audio, sudo, browser enablement, session environment, and SSH.
- `modules/networking.nix`: Tailscale, firewall trust, NetworkManager, Wi-Fi
  power behavior, and USB Wi-Fi stability rules.
- `modules/desktop-wayfire.nix`: SDDM, auto-login, Wayfire default session,
  XDG portals, and keyboard layout.
- `wayfire.nix`: Wayfire package overrides, session package, autostart script,
  Chromium kiosk launch, Wayfire defaults, and Waybar config.
- `modules/admin-panel.nix`: `fauxnix-admin-panel` systemd service, LAN
  firewall access for TCP 8765, and browser desktop environment defaults.
- `modules/agent-runtime.nix`: Ollama local model service, assistant env,
  Faux-pass registry, source installs into `/etc`, and activation-installed
  knowledgebase docs.
- `modules/system-packages.nix`: system package list and short command aliases
  such as `fennix`, `fennix-gui`, `cowriter`, and `fauxnix-assistant`.

Small-agent rule:

Change the narrowest module that owns the behavior. If a change crosses module
boundaries, leave a short note in the commit message and run
`sudo nixos-rebuild build --show-trace` before switching.
