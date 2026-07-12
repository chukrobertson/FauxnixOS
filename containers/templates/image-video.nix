# Image and video editing template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    gimp
    inkscape
    blender
    kdenlive
    ffmpeg
    imagemagick
    darktable
    handbrake
    obs-studio
  ];
}
