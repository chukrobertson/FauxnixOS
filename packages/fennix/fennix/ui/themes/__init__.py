from __future__ import annotations

from pathlib import Path


THEME_DIR = Path(__file__).parent


def load_qss(profile: str) -> str:
    theme_file = THEME_DIR / f"{profile}.qss"
    if theme_file.exists():
        return theme_file.read_text()
    return ""


def apply_theme(app, profile: str) -> None:
    qss = load_qss(profile)
    if qss:
        app.setStyleSheet(qss)


def available_profiles() -> list[str]:
    profiles: list[str] = []
    for f in THEME_DIR.glob("*.qss"):
        name = f.stem
        if name not in ("__init__",):
            profiles.append(name)
    return sorted(profiles)
