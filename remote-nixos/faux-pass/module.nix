{ config, pkgs, lib, ... }:

let
  cfg = config.services.faux-pass;

  # Firecracker for Linux microVMs
  firecracker = pkgs.firecracker;

  # QEMU for Windows VMs
  qemu = pkgs.qemu_full;

  # FreeRDP for Windows app forwarding
  freerdp = pkgs.freerdp;

  # Waypipe for Linux app forwarding
  waypipe = pkgs.waypipe;

  # Guest agent runtime
  guestAgent = pkgs.writeShellApplication {
    name = "faux-pass-guest";
    runtimeInputs = [ pkgs.socat pkgs.jq pkgs.coreutils ];
    text = ''
      #!/bin/sh
      # Faux-pass guest agent - runs inside VM
      # Listens on vsock port 5252 for commands
      exec socat VSOCK-LISTEN:5252,fork EXEC:"/run/current-system/sw/bin/faux-pass-guest-handler"
    '';
  };

  # Guest handler script
  guestHandler = pkgs.writeShellScriptBin "faux-pass-guest-handler" ''
    #!/bin/sh
    set -eu
    read -r cmd
    case "$cmd" in
      list-apps)
        # Return JSON array of available apps
        find /usr/share/applications -name "*.desktop" -exec grep -l "Type=Application" {} \; |
        xargs -r grep -h "^Exec=" |
        sed 's/^Exec=//' |
        sort -u |
        jq -R . | jq -s .
        ;;
      launch)
        read -r app
        exec "$app" &
        echo "launched"
        ;;
      *)
        echo "unknown command: $cmd" >&2
        exit 1
        ;;
    esac
  '';

in {
  options.services.faux-pass = {
    enable = lib.mkEnableOption "Faux-pass VM integration service";

    # Base directory for VM data
    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/faux-pass";
      description = "Directory for VM images, overlays, and configs";
    };

    # Bridge interface for VM networking
    bridgeInterface = lib.mkOption {
      type = lib.types.str;
      default = "faux-pass-br0";
      description = "Bridge interface for VM network access";
    };

    # Default resources per VM
    defaultMemory = lib.mkOption {
      type = lib.types.int;
      default = 2048;
      description = "Default memory in MiB";
    };

    defaultVcpus = lib.mkOption {
      type = lib.types.int;
      default = 2;
      description = "Default vCPU count";
    };

    # Pre-defined VM configurations
    vms = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule {
        options = {
          name = lib.mkOption { type = lib.types.str; };
          type = lib.mkOption {
            type = lib.types.enum [ "linux" "windows" ];
            default = "linux";
          };
          memory = lib.mkOption { type = lib.types.int; default = 2048; };
          vcpus = lib.mkOption { type = lib.types.int; default = 2; };
          baseImage = lib.mkOption { type = lib.types.path; };
          kernel = lib.mkOption { type = lib.types.path; };
          initrd = lib.mkOption { type = lib.types.path; };
          kernelArgs = lib.mkOption { type = lib.types.str; default = "console=ttyS0 reboot=k panic=1 pci=off"; };
          autoStart = lib.mkOption { type = lib.types.bool; default = false; };
          apps = lib.mkOption { type = lib.types.listOf lib.types.str; default = [ ]; };
        };
      });
      default = { };
    };
  };

  config = lib.mkIf cfg.enable {
    # Create data directories
    system.activationScripts.faux-pass-dirs = ''
      mkdir -p ${cfg.dataDir}/{images,overlays,configs,sockets,logs}
      chown -R faux-pass:faux-pass ${cfg.dataDir} 2>/dev/null || true
    '';

    # Network bridge for VMs
    networking.bridges.${cfg.bridgeInterface} = {
      interface = "eth0"; # Adjust based on primary interface
      dhcp = true;
    };

    # Firecracker binary
    environment.systemPackages = with pkgs; [
      firecracker
      qemu
      freerdp
      waypipe
      guestAgent
      guestHandler
      socat
      jq
    ];

    # Faux-pass manager daemon
    systemd.services.faux-pass-manager = {
      description = "Faux-pass VM Manager";
      after = [ "network-online.target" "libvirtd.service" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "notify";
        User = "faux-pass";
        Group = "faux-pass";
        ExecStart = "${pkgs.python3}/bin/python3 -m faux_pass.manager";
        Restart = "on-failure";
        RestartSec = 5;
        Environment = [
          "FAUX_PASS_DATA_DIR=${cfg.dataDir}"
          "FAUX_PASS_BRIDGE=${cfg.bridgeInterface}"
        ];
      };
    };

    # Socket activation for API
    systemd.services.faux-pass-api = {
      description = "Faux-pass API (socket activated)";
      serviceConfig = {
        Type = "exec";
        User = "faux-pass";
        Group = "faux-pass";
        ExecStart = "${pkgs.python3}/bin/python3 -m faux_pass.api";
        Environment = [
          "FAUX_PASS_DATA_DIR=${cfg.dataDir}"
        ];
        StandardInput = "socket";
      };
    };

    systemd.socket."faux-pass-api" = {
      description = "Faux-pass API Socket";
      wantedBy = [ "sockets.target" ];
      socketConfig = {
        ListenStream = "${cfg.dataDir}/sockets/api.sock";
        SocketUser = "faux-pass";
        SocketGroup = "faux-pass";
        SocketMode = "0660";
      };
    };

    # User for running VMs
    users.users.faux-pass = {
      isSystemUser = true;
      group = "faux-pass";
      home = cfg.dataDir;
      shell = pkgs.bash;
    };

    users.groups.faux-pass = { };

    # KVM access
    users.users.faux-pass.extraGroups = [ "kvm" "libvirt" ];

    # CLI tool
    environment.systemPackages = with pkgs; [
      (writeShellApplication {
        name = "faux-pass";
        runtimeInputs = [ pkgs.python3 pkgs.jq pkgs.curl ];
        text = ''
          #!/bin/sh
          exec python3 -m faux_pass.cli "$@"
        '';
      })
    ];

    # Fauxd API extensions (if fauxd enabled)
    systemd.services.fauxd = lib.mkIf config.services.fauxd.enable {
      serviceConfig.Environment = lib.optionalString (config.services.fauxd.enable) "
        FAUX_PASS_SOCKET=${cfg.dataDir}/sockets/api.sock
      ";
    };
  };
}