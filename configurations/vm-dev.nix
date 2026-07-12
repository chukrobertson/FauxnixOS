{ config, lib, pkgs, ... }:

{
  boot.loader.systemd-boot.enable = true;

  networking.hostName = "fauxnix-dev";
  networking.useDHCP = true;

  services.openssh = {
    enable = true;
    settings.PermitRootLogin = lib.mkForce "yes";
    settings.PasswordAuthentication = true;
  };

  users.users.root.initialPassword = "fauxnix";
  users.users.chxk = {
    isNormalUser = true;
    uid = 1000;
    extraGroups = [ "wheel" ];
    initialPassword = "fauxnix";
  };

  security.sudo.wheelNeedsPassword = false;

  virtualisation.diskSize = 32768;

  environment.systemPackages = with pkgs; [
    git
    neovim
    curl
    htop
    btrfs-progs
    python3
    waypipe
  ];

  services.ollama.enable = true;

  system.stateVersion = "26.05";
}
