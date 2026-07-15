{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix.fauxnixos;
in
{
  options.fauxnix.fauxnixos = {
    enable = lib.mkEnableOption "FauxnixOS services — Nexus, threads, GNOME extensions, workspace infrastructure";
    enableNexus = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable the Nexus host daemon (CPU-intensive — disable on low-power machines)";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.nexus = lib.mkIf cfg.enableNexus {
      description = "Nexus Host Daemon";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" "ollama.service" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.python3}/bin/python3 -m nexus";
        Restart = "always";
        RestartSec = 10;
        Environment = [
          "PYTHONPATH=/home/chxk/Projects/fauxnix-core/packages/nexus:/home/chxk/Projects/fauxnix-core/packages/fauxnix-tools"
        ];
      };
    };

    system.activationScripts.fauxnixosSetup = ''
      mkdir -p /var/lib/workspaces
      mkdir -p /var/lib/workspaces-shared
      mkdir -p /run/nexus
      chmod 755 /run/nexus
    '';

    environment.etc."xdg/autostart/nexus-welcome.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Nexus Welcome
      Exec=/home/chxk/Projects/fauxnix-core/scripts/nexus-welcome.sh
      Terminal=false
      NoDisplay=true
      X-GNOME-Autostart-enabled=true
      X-GNOME-Autostart-Delay=3
    '';

    environment.etc."skel/.local/share/gnome-shell/extensions/fennix@fauxnix.local".source =
      /home/chxk/Projects/fauxnix-core/modules/gnome/fennix-extension;

    programs.dconf.profiles.user.databases = [
      {
        settings = {
          "org/gnome/shell" = {
            enabled-extensions = [ "fennix@fauxnix.local" ];
          };
        };
      }
    ];

    environment.variables.PATH = [ "$HOME/.local/bin" ];
  };
}
