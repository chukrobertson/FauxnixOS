"""Thin wrapper for importing archivist core modules.

At runtime the archivist Python source may be:
1. In the Nix store as `archivist_app` (set via ARCHIVIST_SRC wrapper script)
  2. In E:/Archivist/app during local development (appears as `app` package)
3. Unavailable — the app runs with minimal functionality

This module normalizes the import so callers always use `archivist_app`.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

_loaded = False
_load_error: str | None = None
_archivist_app: ModuleType | None = None


def _find_archivist_src() -> Path | None:
    env = os.getenv("ARCHIVIST_SRC")
    if env:
        p = Path(env).resolve()
        if p.is_dir():
            app_dir = p / "app" if (p / "app" / "__init__.py").exists() else p
            if (app_dir / "__init__.py").exists():
                return app_dir
            # Maybe the env points to the app/ directory itself
            if (p / "__init__.py").exists():
                return p

    # Development fallbacks
    dev_candidates = [
        Path.home() / "Fauxnix" / "remote-nixos" / "archivist_app",
        Path("E:") / "Archivist" / "app",
        Path.home() / "Archivist" / "app",
    ]
    for c in dev_candidates:
        if c.is_dir() and (c / "__init__.py").exists():
            return c
    return None


def available() -> bool:
    global _loaded, _load_error
    if _loaded:
        return True
    if _load_error:
        return False
    src = _find_archivist_src()
    if src is None:
        _load_error = (
            "archivist source not found. Set ARCHIVIST_SRC env var "
            "or sync app source with sync-archivist-source.ps1."
        )
        return False
    parent = src.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    # Determine module name: the directory name becomes the package name
    module_name = src.name  # "archivist_app" in Nix store, "app" in dev
    try:
        mod = importlib.import_module(module_name)
        # If it's "app" in dev, alias to "archivist_app"
        if module_name == "app":
            sys.modules["archivist_app"] = mod
        _archivist_app = mod
        _loaded = True
        return True
    except ImportError as e:
        _load_error = f"cannot import '{module_name}': {e}"
        return False


def import_module(name: str = "archivist_app") -> ModuleType | None:
    """Return the archivist top-level module, or None on failure."""
    if not _loaded:
        available()
    return sys.modules.get(name)


def load_error() -> str | None:
    return _load_error
