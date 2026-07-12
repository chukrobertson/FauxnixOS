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


def install_for_workload(workload: str) -> list[str]:
    WORKLOAD_PACKAGES: dict[str, list[str]] = {
        "python": ["python3", "python3.pkgs.pip", "python3.pkgs.ipython"],
        "rust": ["cargo", "rustc", "rust-analyzer"],
        "documents": ["pandoc", "zathura", "texlive.combined.scheme-small"],
        "writing": ["pandoc", "neovim", "texlive.combined.scheme-small"],
        "media": ["ffmpeg", "gimp", "inkscape"],
        "web": ["nodejs", "nodePackages.typescript", "vscode"],
        "data": ["python3", "python3.pkgs.pandas", "python3.pkgs.jupyter"],
        "ml": ["python3", "python3.pkgs.torch", "python3.pkgs.jupyter"],
        "nix": ["nixpkgs-fmt", "nixd", "nil"],
    }
    return WORKLOAD_PACKAGES.get(workload, [])
