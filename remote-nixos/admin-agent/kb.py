from __future__ import annotations

import os
from pathlib import Path


KB_DIR = Path(os.environ.get("FAUXNIX_KB_DIR", os.path.expanduser("~/.config/fauxnix/kb")))
MANAGER_KB = "manager.md"

MODULE_KB_MAP: dict[str, str] = {
    "configuration.nix": "configuration.md",
    "wayfire.nix": "wayfire.md",
    "admin-panel.nix": "admin-panel.md",
    "wall-display.nix": "wall-display.md",
    "smb-shares.nix": "smb-shares.md",
    "archivist-web.nix": "archivist-web.md",
    "agent-runtime.nix": "agent-runtime.md",
    "base-system.nix": "base-system.md",
    "desktop-wayfire.nix": "desktop-wayfire.md",
    "networking.nix": "networking.md",
    "system-packages.nix": "system-packages.md",
    "local-packages.nix": "local-packages.md",
}

MODULE_DESCRIPTIONS: dict[str, str] = {
    "configuration.nix": "Top-level NixOS config — imports modules, sets stateVersion, passes fauxnix package set to modules",
    "wayfire.nix": "Wayfire compositor config — session autostart, Chromium kiosk launch, package imports",
    "admin-panel.nix": "Admin Panel web service (port 8765) — system status, wall display controls, drive inbox",
    "wall-display.nix": "Wall Display kiosk service (port 8780) — family calendar, weather, settings",
    "smb-shares.nix": "Tailscale-bound Samba shares — archive access from tailnet devices",
    "archivist-web.nix": "Archivist browser UI (port 8776) — FastAPI service for archive search and drive inbox",
    "agent-runtime.nix": "Agent runtime paths — workspace roots, knowledge dirs, snapshot paths",
    "base-system.nix": "Base NixOS config — bootloader (systemd-boot), firmware, graphics drivers, locale",
    "desktop-wayfire.nix": "Desktop Wayfire profile — SDDM auto-login, Wayfire session, wallpaper",
    "networking.nix": "Network config — Tailscale, firewall rules, allowed ports",
    "system-packages.nix": "System package manifest — imports all fauxnix packages into environment.systemPackages",
    "local-packages.nix": "Local package definitions — writeShellApplication derivations for all fauxnix tools",
}


def ensure_kb_dir() -> Path:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    return KB_DIR


def kb_path(name: str) -> Path:
    return KB_DIR / name


def read_kb(name: str) -> str:
    path = kb_path(name)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def write_kb(name: str, content: str) -> None:
    ensure_kb_dir()
    kb_path(name).write_text(content, encoding="utf-8")


def list_kbs() -> list[dict]:
    ensure_kb_dir()
    entries = []
    for path in sorted(KB_DIR.glob("*.md")):
        entries.append({
            "name": path.name,
            "path": str(path),
            "size": path.stat().st_size,
        })
    return entries


def get_module_for_kb(kb_name: str) -> str | None:
    for module, kb in MODULE_KB_MAP.items():
        if kb == kb_name:
            return module
    return None


def init_default_kbs() -> list[str]:
    ensure_kb_dir()
    initialized = []
    for module, kb_file in MODULE_KB_MAP.items():
        if not kb_path(kb_file).exists():
            desc = MODULE_DESCRIPTIONS.get(module, "Fauxnix NixOS module")
            write_kb(kb_file, f"# {module}\n\n{desc}\n\n## Purpose\n\nTBD\n\n## Key Options\n\nTBD\n\n## Dependencies\n\nTBD\n\n## Notes\n\nTBD\n")
            initialized.append(kb_file)
    if not kb_path(MANAGER_KB).exists():
        write_kb(MANAGER_KB, "# Fauxnix Manager\n\nSource of truth for the Fauxnix Admin agent system.\n\n## Managed Modules\n\n" + "\n".join(f"- {k}: {v}" for k, v in MODULE_DESCRIPTIONS.items()) + "\n")
        initialized.append(MANAGER_KB)
    return initialized
