# Audio production template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    audacity
    ardour
    lmms
    ffmpeg
    sox
    musescore
    sound-juicer
  ];
}
