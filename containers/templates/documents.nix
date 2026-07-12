# Document creation, editing, and publishing template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    pandoc
    texlive.combined.scheme-medium
    zathura
    libreoffice
    calibre
    neovim
    ghostscript
    poppler_utils
    aspell
    aspellDicts.en
    hunspell
    hunspellDicts.en_US
  ];
}
