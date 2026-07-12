# Media / Design template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    ffmpeg
    gimp
    inkscape
    blender
    audacity
    imagemagick
  ];
}
