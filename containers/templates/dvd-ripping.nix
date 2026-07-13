# DVD Ripping & Media Conversion template
# Requires --bind=/dev/sr0:/dev/sr0 for optical drive access
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    handbrake
    makemkv
    libdvdcss
    ffmpeg
    vlc
    mkvtoolnix
    mediainfo
    cdrtools
  ];
}
