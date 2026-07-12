# Research template — browsers, note-taking, clipboard, reference management
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    firefox
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
