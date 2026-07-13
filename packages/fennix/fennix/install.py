from __future__ import annotations

import subprocess


def install_package(pkg: str) -> bool:
    result = subprocess.run(
        ["nix-shell", "-p", pkg, "--run", "echo installed"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def install_profile(pkg: str) -> bool:
    result = subprocess.run(
        ["nix", "profile", "install", f"nixpkgs#{pkg}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def install_packages(packages: list[str], method: str = "shell") -> dict[str, bool]:
    results: dict[str, bool] = {}
    installer = install_package if method == "shell" else install_profile
    for pkg in packages:
        results[pkg] = installer(pkg)
    return results


def install_template(template_name: str) -> list[str]:
    packages = packages_for_template(template_name)
    results: list[str] = []
    for pkg in packages:
        if install_package(pkg):
            results.append(pkg)
    return results


def packages_for_template(template_name: str) -> list[str]:
    return TEMPLATE_PACKAGES.get(template_name, [])


def fine_tune(thread_description: str) -> list[str]:
    desc_lower = thread_description.lower()
    installed: list[str] = []

    for template, packages in TEMPLATE_PACKAGES.items():
        score = sum(1 for kw in _template_keywords(template) if kw in desc_lower)
        if score >= 2:
            for pkg in packages:
                if pkg not in installed:
                    if install_package(pkg):
                        installed.append(pkg)
            break

    if not installed:
        for pkg in TEMPLATE_PACKAGES.get("coding", []):
            if install_package(pkg):
                installed.append(pkg)

    return installed


def _template_keywords(template: str) -> list[str]:
    return TEMPLATE_KEYWORDS.get(template, [template])


TEMPLATE_PACKAGES: dict[str, list[str]] = {
    "ml-python": [
        "python3", "python3.pkgs.torch", "python3.pkgs.torchvision",
        "python3.pkgs.jupyter", "python3.pkgs.matplotlib",
        "python3.pkgs.numpy", "python3.pkgs.pandas",
        "python3.pkgs.scipy", "python3.pkgs.scikit-learn",
    ],
    "coding": [
        "git", "neovim", "gcc", "gnumake", "cmake", "gdb",
        "python3", "nodejs", "cargo", "rustc", "go",
        "nixpkgs-fmt", "nixd", "ripgrep", "fd", "jq", "tmux",
    ],
    "rust-dev": [
        "cargo", "rustc", "rust-analyzer", "rustfmt", "clippy", "gcc", "gdb",
    ],
    "web-dev": [
        "nodejs", "nodePackages.typescript", "nodePackages.pnpm", "vscode", "git",
    ],
    "writing": [
        "pandoc", "zathura", "texlive.combined.scheme-small",
        "neovim", "aspell", "aspellDicts.en",
    ],
    "documents": [
        "pandoc", "texlive.combined.scheme-medium", "zathura",
        "libreoffice", "calibre", "neovim", "ghostscript",
        "poppler_utils", "aspell", "aspellDicts.en",
    ],
    "research": [
        "firefox", "obsidian", "zotero", "zathura", "pandoc",
        "neovim", "xclip", "wl-clipboard", "ripgrep", "fd",
    ],
    "audio": [
        "audacity", "ardour", "lmms", "ffmpeg", "sox", "musescore",
    ],
    "image-video": [
        "gimp", "inkscape", "blender", "kdenlive", "ffmpeg",
        "imagemagick", "darktable", "handbrake", "obs-studio",
    ],
    "gaming": [
        "steam", "lutris", "wine", "winetricks",
        "gamemode", "mangohud", "protonup-qt",
    ],
    "dvd-ripping": [
        "handbrake", "makemkv", "libdvdcss", "ffmpeg",
        "vlc", "mkvtoolnix", "mediainfo", "cdrtools",
    ],
    "emulation": [
        "retroarch", "retroarch-assets", "dolphin-emu", "pcsx2",
        "ppsspp", "mupen64plus", "snes9x", "mgba",
        "duckstation", "flycast", "melonDS", "yuzu",
    ],
    "python": ["python3", "python3.pkgs.pip", "python3.pkgs.ipython"],
    "rust": ["cargo", "rustc", "rust-analyzer"],
    "data": ["python3", "python3.pkgs.pandas", "python3.pkgs.jupyter"],
    "media": ["ffmpeg", "gimp", "inkscape"],
    "nix": ["nixpkgs-fmt", "nixd", "nil"],
}


TEMPLATE_KEYWORDS: dict[str, list[str]] = {
    "ml-python": ["ml", "machine learning", "pytorch", "jupyter", "train", "model"],
    "coding": ["code", "programming", "develop", "compile", "debug", "git"],
    "rust-dev": ["rust", "cargo", "rustc"],
    "web-dev": ["web", "website", "frontend", "backend", "nodejs", "npm"],
    "writing": ["write", "blog", "article", "essay", "book", "novel"],
    "documents": ["document", "pdf", "office", "latex", "publish", "report"],
    "research": ["research", "note", "study", "browser", "paper", "reference"],
    "audio": ["audio", "music", "sound", "podcast", "record", "mix"],
    "image-video": ["image", "photo", "video", "edit", "design", "gimp", "blender"],
    "gaming": ["game", "gaming", "steam", "play", "proton"],
    "dvd-ripping": ["dvd", "bluray", "rip", "handbrake", "makemkv", "encode"],
    "emulation": ["emulate", "emulator", "rom", "retro", "retroarch", "dolphin"],
}
