# Python ML / Data Science template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    python3
    python3.pkgs.pip
    python3.pkgs.torch
    python3.pkgs.torchvision
    python3.pkgs.jupyter
    python3.pkgs.matplotlib
    python3.pkgs.numpy
    python3.pkgs.pandas
    python3.pkgs.scipy
    python3.pkgs.scikit-learn
  ];
}
