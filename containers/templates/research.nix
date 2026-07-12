# Research template — browsers, note-taking, clipboard, reference management
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    firefox
    google-chrome
    obsidian
    zotero
    zathura
    pandoc
    neovim
    xclip
    wl-clipboard
    glow
    ripgrep
    fd
  ];
}
