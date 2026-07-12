{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix.membrie;
in
{
  options.fauxnix.membrie = {
    enable = lib.mkEnableOption "Membrie — AI-powered session tracking and memory companion";
    user = lib.mkOption {
      type = lib.types.str;
      default = "fauxnix";
      description = "User to run Membrie as";
    };
    otgPort = lib.mkOption {
      type = lib.types.port;
      default = 8920;
      description = "Port for the OTG mobile web interface";
    };
    kioskEnable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable kiosk dashboard on local display";
    };
  };

  config = lib.mkIf cfg.enable {
    # ── systemd user service: Membrie background daemon ──────────
    systemd.user.services.membrie-daemon = {
      description = "Membrie Activity Tracker & Memory Companion";
      wantedBy = [ "default.target" ];
      after = [ "graphical-session.target" "ollama.service" ];
      partOf = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.python3}/bin/python3 -m membrie";
        Restart = "always";
        RestartSec = 5;
        Environment = [
          "FAUXNIX_MEMBRIE_USER=${cfg.user}"
          "MEMBRIE_OTG_PORT=${toString cfg.otgPort}"
        ];
      };
    };

    # ── systemd user service: OTG web server ─────────────────────
    systemd.user.services.membrie-otg = {
      description = "Membrie OTG Mobile Web Server";
      wantedBy = [ "default.target" ];
      after = [ "membrie-daemon.service" ];
      partOf = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.python3}/bin/python3 -m membrie.web.otg_server";
        Restart = "always";
        RestartSec = 3;
      };
    };

    environment.systemPackages = with pkgs; [
      xdotool
      wmctrl
      libnotify
    ];
  };
}
