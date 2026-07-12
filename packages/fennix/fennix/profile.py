from __future__ import annotations

import json
from pathlib import Path


PROFILE_META: dict[str, dict] = {
    "headless": {
        "name": "Headless",
        "description": "No desktop environment — SSH access only",
        "icon": "terminal",
        "compositor": None,
    },
    "win11": {
        "name": "Windows 11",
        "description": "Bottom taskbar, centered launcher, acrylic blur, rounded corners",
        "icon": "windows",
        "compositor": "labwc",
        "compositor_config": "labwc-win11.xml",
        "qss_theme": "win11",
    },
    "macos": {
        "name": "macOS",
        "description": "Top menu bar, bottom dock, frosted glass, spotlight search",
        "icon": "apple",
        "compositor": "labwc",
        "compositor_config": "labwc-macos.xml",
        "qss_theme": "macos",
    },
}


def get_profile(profile_name: str) -> dict | None:
    return PROFILE_META.get(profile_name)


def apply_profile(app, profile_name: str) -> None:
    profile = get_profile(profile_name)
    if not profile:
        return
    qss_theme = profile.get("qss_theme")
    if qss_theme:
        from fennix.ui.themes import apply_theme
        apply_theme(app, qss_theme)


def profile_description(profile_name: str) -> str:
    profile = get_profile(profile_name)
    if profile:
        return f"{profile['name']} — {profile['description']}"
    return profile_name


def list_profiles() -> list[dict]:
    return [
        {"id": name, "name": meta["name"], "description": meta["description"]}
        for name, meta in PROFILE_META.items()
    ]


def read_profile_from_manifest(workspace_root: str) -> str:
    manifest_path = Path(workspace_root) / "ws-manifest.json"
    if not manifest_path.exists():
        return "headless"
    try:
        manifest = json.loads(manifest_path.read_text())
        return manifest.get("nix", {}).get("profile", "headless")
    except (json.JSONDecodeError, KeyError):
        return "headless"
