{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix.immutable-base;
in
{
  options.fauxnix.immutable-base = {
    enable = lib.mkEnableOption "Immutable NixOS base — read-only root with tmpfs overlay. Only essential services run. Threads are the interactive layer.";

    persistentPaths = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "/home"
        "/var/lib/workspaces"
        "/var/lib/workspaces-shared"
        "/var/lib/ollama"
        "/var/lib/systemd"
        "/var/log"
      ];
      description = "Paths that persist across reboots (must be on btrfs subvolumes)";
    };

    autoStartThreads = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = "Thread names to auto-start on boot";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.initrd.systemd.enable = true;

    fileSystems."/" = {
      device = "tmpfs";
      fsType = "tmpfs";
      options = [ "defaults" "size=4G" "mode=755" ];
    };

    fileSystems."/nix" = lib.mkIf (!config.boot.isContainer) {
      device = "/dev/disk/by-label/NIXROOT";
      fsType = "btrfs";
      options = [ "subvol=@nix" "ro" "noatime" ];
      neededForBoot = true;
    };

    fileSystems."/boot" = lib.mkIf (!config.boot.isContainer) {
      device = "/dev/disk/by-label/ESP";
      fsType = "vfat";
      options = [ "noatime" ];
    };

    boot.initrd.supportedFilesystems = [ "btrfs" "vfat" ];

    services.openssh = {
      enable = true;
      settings.PermitRootLogin = lib.mkForce "no";
      settings.PasswordAuthentication = lib.mkForce false;
    };

    networking.firewall.allowedTCPPorts = [ 22 ];

    systemd.services.nexus = {
      description = "Nexus Host Daemon — thread orchestration and ML pipeline";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" "ollama.service" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.python3}/bin/python3 -m nexus";
        Restart = "always";
        RestartSec = 10;
        Environment = [
          "PYTHONPATH=/fauxnix-core/packages/nexus:/fauxnix-core/packages/fauxnix-tools"
        ];
      };
    };

    services.ollama = {
      enable = true;
    };

    boot.kernel.sysctl = {
      "kernel.modules_disabled" = lib.mkDefault 1;
    };

    security.sudo.execWheelOnly = true;

    environment.systemPackages = with pkgs; [
      git
      btrfs-progs
      python3
      curl
      htop
    ];

    environment.variables = {
      PATH = [ "$HOME/.local/bin" ];
    };

    users.users.root.initialPassword = lib.mkForce "!";

    system.activationScripts.nexusDir = ''
      mkdir -p /run/nexus
      chmod 777 /run/nexus
    '';

    system.activationScripts.fauxnixMounts = ''
      for path in ${lib.concatStringsSep " " cfg.persistentPaths}; do
        mkdir -p "$path"
      done
      mkdir -p /etc/nixos
      mkdir -p /var/lib/nixos
    '';

    system.stateVersion = "26.05";
  };
}
