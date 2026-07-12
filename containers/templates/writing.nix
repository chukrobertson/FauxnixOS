# Writing / Document template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    pandoc
    zathura
    texlive.combined.scheme-small
    neovim
    aspell
    aspellDicts.en
  ];
}
