# Emulation & Retro Gaming template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    retroarch
    retroarch-assets
    dolphin-emu
    pcsx2
    ppsspp
    mupen64plus
    snes9x
    mgba
    duckstation
    flycast
    melonDS
    yuzu
    steam
    gamemode
    mangohud
  ];
}
