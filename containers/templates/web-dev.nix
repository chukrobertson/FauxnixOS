# Web development template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    nodejs
    nodePackages.typescript
    nodePackages.pnpm
    vscode
    git
  ];
}
