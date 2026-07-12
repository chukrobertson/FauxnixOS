{ config, lib, pkgs, ... }:

{
  boot.isContainer = true;

  networking.hostName = lib.mkDefault "workspace";
  networking.useDHCP = false;

  users.users.chxk = {
    isNormalUser = true;
    uid = 1000;
    extraGroups = [ "wheel" ];
    initialPassword = "workspace";
  };

  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "no";
    settings.PasswordAuthentication = true;
    settings.UseDns = false;
  };

  environment.systemPackages = with pkgs; [
    git
    neovim
    curl
    htop
    btrfs-progs
  ];

  system.stateVersion = "26.05";
}
