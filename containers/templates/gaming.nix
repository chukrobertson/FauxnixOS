# Gaming template — Steam, Lutris, GPU support
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    steam
    lutris
    wine
    winetricks
    gamemode
    mangohud
    goverlay
    protonup-qt
    vulkan-tools
    glxinfo
  ];

  programs.steam.enable = true;
  programs.gamemode.enable = true;
}
