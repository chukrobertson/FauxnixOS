# General coding template — Fennix installs language-specific tools
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    git
    neovim
    gcc
    gnumake
    cmake
    gdb
    python3
    nodejs
    cargo
    rustc
    go
    nixpkgs-fmt
    nixd
    shellcheck
    ripgrep
    fd
    jq
    tmux
  ];
}
