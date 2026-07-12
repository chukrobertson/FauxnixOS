{ config, lib, pkgs, ... }:

let
  fennix-script = pkgs.writeShellScriptBin "fennix-start" ''
    export PATH="${pkgs.python3}/bin:$PATH"
    export PYTHONPATH="/fauxnix-core/packages/fennix:/fauxnix-core/packages/fauxnix-tools"
    export FENNIX_AUTO_INGEST=false
    exec ${pkgs.python3}/bin/python3 -m fennix
  '';
in
{
  boot.isContainer = true;

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

  systemd.services.fennix = {
    description = "Fennix In-Thread Assistant";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];
    serviceConfig = {
      Type = "simple";
      ExecStart = "${fennix-script}/bin/fennix-start";
      Restart = "always";
      RestartSec = 5;
      PassEnvironment = "FENNIX_THREAD_NAME";
    };
  };

  environment.systemPackages = with pkgs; [
    git
    neovim
    curl
    htop
    btrfs-progs
    python3
    python3.pkgs.psutil
  ];

  system.stateVersion = "26.05";
}
