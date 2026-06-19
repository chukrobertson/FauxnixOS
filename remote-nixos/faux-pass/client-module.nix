{ config, pkgs, lib, ... }:

let
  cfg = config.services.faux-pass.client;

  # Client manager daemon
  managerScript = pkgs.writeShellApplication {
    name = "faux-pass-manager";
    runtimeInputs = with pkgs; [ python3 python3Packages.websockets python3Packages.aiohttp python3Packages.pyyaml ];
    text = ''
      #!/bin/sh
      exec python3 -m faux_pass.client.manager "$@"
    '';
  };

  # Provider client (connects to remote Providers)
  providerClientScript = pkgs.writeShellApplication {
    name = "faux-pass-provider-client";
    runtimeInputs = with pkgs; [ python3 python3Packages.websockets python3Packages.tailscale ];
    text = ''
      #!/bin/sh
      exec python3 -m faux_pass.client.provider_client "$@"
    '';
  };

  # CLI tool
  cliScript = pkgs.writeShellApplication {
    name = "faux-pass";
    runtimeInputs = with pkgs; [ python3 python3Packages.click python3Packages.rich python3Packages.pyyaml ];
    text = ''
      #!/bin/sh
      exec python3 -m faux_pass.client.cli "$@"
    '';
  };

  # API server (socket-activated)
  apiScript = pkgs.writeShellApplication {
    name = "faux-pass-api";
    runtimeInputs = with pkgs; [ python3 python3Packages.aiohttp python3Packages.aiohttp-wsgi ];
    text = ''
      #!/bin/sh
      exec python3 -m faux_pass.client.api "$@"
    '';
  };

  # Local VM runtime: Firecracker + QEMU
  vmRuntime = with pkgs; [ firecracker qemu_full freerdp waypipe ];

in {
  options.services.faux-pass.client = {
    enable = lib.mkEnableOption "Faux-pass Client (FauxnixOS side)";

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/faux-pass";
      description = "Directory for VM images, overlays, configs, sockets";
    };

    # Local VM defaults
    defaultMemory = lib.mkOption {
      type = lib.types.int;
      default = 2048;
    };
    defaultVcpus = lib.mkOption {
      type = lib.types.int;
      default = 2;
    };

    # Pre-configured local VMs
    vms = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule {
        options = {
          name = lib.mkOption { type = lib.types.str; };
          type = lib.mkOption {
            type = lib.types.enum [ "linux" "windows" ];
            default = "linux";
          };
          memory = lib.mkOption { type = lib.types.int; };
          vcpus = lib.mkOption { type = lib.types.int; };
          baseImage = lib.mkOption { type = lib.types.nullOr lib.types.path; default = null; };
          kernel = lib.mkOption { type = lib.types.nullOr lib.types.path; default = null; };
          initrd = lib.mkOption { type = lib.types.nullOr lib.types.path; default = null; };
          kernelArgs = lib.mkOption { type = lib.types.str; default = "console=ttyS0 reboot=k panic=1 pci=off"; };
          autoStart = lib.mkOption { type = lib.types.bool; default = false; };
          apps = lib.mkOption { type = lib.types.listOf lib.types.str; default = [ ]; };
        };
      });
      default = { };
    };

    # Remote Provider connections
    providers = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule {
        options = {
          name = lib.mkOption { type = lib.types.str; };
          tailscaleName = lib.mkOption { type = lib.types.str; description = "Tailscale MagicDNS name (e.g. nexus)"; };
          port = lib.mkOption { type = lib.types.int; default = 4433; };
          pskFile = lib.mkOption { type = lib.types.path; description = "Pre-shared key file"; };
          autoConnect = lib.mkOption { type = lib.types.bool; default = true; };
          trusted = lib.mkOption { type = lib.types.bool; default = false; };
        };
      });
      default = { };
    };

    # API socket
    apiSocket = lib.mkOption {
      type = lib.types.str;
      default = "/run/faux-pass/api.sock";
    };
  };

  config = lib.mkIf cfg.enable {
    # Data directories
    system.activationScripts.faux-pass-client-dirs = ''
      mkdir -p ${cfg.dataDir}/{images,overlays,configs,sockets,logs}
      mkdir -p $(dirname ${cfg.apiSocket})
      chown -R faux-pass:faux-pass ${cfg.dataDir} 2>/dev/null || true
      chown faux-pass:faux-pass $(dirname ${cfg.apiSocket}) 2>/dev/null || true
    '';

    # Packages
    environment.systemPackages = with pkgs; [
      managerScript
      providerClientScript
      cliScript
      apiScript
      vmRuntime
      socat
      jq
      curl
      tailscale
    ];

    # User for running VMs
    users.users.faux-pass = {
      isSystemUser = true;
      group = "faux-pass";
      home = cfg.dataDir;
      shell = pkgs.bash;
      extraGroups = [ "kvm" "libvirt" "network" ];
    };
    users.groups.faux-pass = { };

    # Tailscale (required for Provider discovery)
    services.tailscale.enable = true;

    # Manager daemon (local VMs + provider connections)
    systemd.services.faux-pass-manager = {
      description = "Faux-pass Client Manager";
      after = [ "network-online.target" "tailscaled.service" "libvirtd.service" ];
      wants = [ "network-online.target" "tailscaled.service" ];
      serviceConfig = {
        Type = "notify";
        User = "faux-pass";
        Group = "faux-pass";
        ExecStart = "${managerScript}/bin/faux-pass-manager";
        Restart = "on-failure";
        RestartSec = 5;
        Environment = [
          "FAUX_PASS_DATA_DIR=${cfg.dataDir}"
          "FAUX_PASS_API_SOCKET=${cfg.apiSocket}"
        ];
      };
    };

    # API server (socket-activated)
    systemd.services.faux-pass-api = {
      description = "Faux-pass Client API";
      serviceConfig = {
        Type = "exec";
        User = "faux-pass";
        Group = "faux-pass";
        ExecStart = "${apiScript}/bin/faux-pass-api";
        Environment = [
          "FAUX_PASS_DATA_DIR=${cfg.dataDir}"
          "FAUX_PASS_API_SOCKET=${cfg.apiSocket}"
        ];
        StandardInput = "socket";
      };
    };

    systemd.socket."faux-pass-api" = {
      description = "Faux-pass Client API Socket";
      wantedBy = [ "sockets.target" ];
      socketConfig = {
        ListenStream = "${cfg.apiSocket}";
        SocketUser = "faux-pass";
        SocketGroup = "faux-pass";
        SocketMode = "0660";
      };
    };

    # Auto-start configured VMs
    systemd.services."faux-pass-vm@" = {
      description = "Faux-pass Local VM %i";
      after = [ "faux-pass-manager.service" ];
      serviceConfig = {
        Type = "oneshot";
        User = "faux-pass";
        Group = "faux-pass";
        ExecStart = "${managerScript}/bin/faux-pass-manager vm-start %i";
        RemainAfterExit = true;
        ExecStop = "${managerScript}/bin/faux-pass-manager vm-stop %i";
      };
    };

    lib.forEach (builtins.attrNames cfg.vms) (vmName: 
      lib.mkIf cfg.vms.${vmName}.autoStart {
        systemd.services."faux-pass-vm-${vmName}" = {
          enable = true;
          wantedBy = [ "multi-user.target" ];
        };
      }
    );

    # Fauxd integration (if enabled)
    systemd.services.fauxd = lib.mkIf config.services.fauxd.enable {
      serviceConfig.Environment = lib.optionalString (config.services.fauxd.enable) "
        FAUX_PASS_API_SOCKET=${cfg.apiSocket}
      ";
    };
  };
}