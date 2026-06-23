# Fauxnix Archivist host manifest. Keep this file small: broad system
# behavior belongs in ./modules, and local package/script definitions belong
# in ./modules/local-packages.nix.

{ config, lib, pkgs, ... }:

let
  fauxnixLocal = import ./modules/local-packages.nix {
    inherit pkgs lib;
  };
in
{
  _module.args.fauxnix = fauxnixLocal;

  nixpkgs.config = {
    allowUnfree = true;
  };

  imports = [
    ./hardware-configuration.nix
    ./wayfire.nix
    ./modules/base-system.nix
    ./modules/networking.nix
    ./modules/agent-runtime.nix
    ./modules/archivist-web.nix
    ./modules/node-desktop.nix
    ./modules/smb-shares.nix
    ./modules/desktop-wayfire.nix
    ./modules/wall-display.nix
    ./modules/system-packages.nix
  ];

  # This value determines the NixOS release from which stateful defaults such
  # as file locations and database versions are derived. Do not change it
  # casually; read `man configuration.nix` first.
  system.stateVersion = "26.05";
}
