{ config, lib, pkgs, ... }:

{
  imports = [
    /home/chxk/Projects/fauxnix-core/modules/immutable-base.nix
  ];

  fauxnix.immutable-base.enable = true;

  boot.isContainer = false;
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "fauxnix-immutable";
  networking.useDHCP = false;
  networking.interfaces.eth0.useDHCP = true;

  users.users.chxk = {
    isNormalUser = true;
    uid = 1000;
    extraGroups = [ "wheel" ];
    initialPassword = "fauxnix";
    openssh.authorizedKeys.keys = [];
  };

  users.users.root.openssh.authorizedKeys.keys = [];

  system.stateVersion = "26.05";
}
