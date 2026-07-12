{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix.archivist;
in
{
  options.fauxnix.archivist = {
    enable = lib.mkEnableOption "Archivist — AI-powered intelligent file manager";
    user = lib.mkOption {
      type = lib.types.str;
      default = "fauxnix";
      description = "User to run Archivist as";
    };
    defaultFileManager = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Set Archivist as the default file manager";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.archivist-daemon = {
      description = "Archivist Smart File Manager Daemon";
      wantedBy = [ "default.target" ];
      after = [ "graphical-session.target" ];
      partOf = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.python3}/bin/python3 -m archivist";
        Restart = "always";
        RestartSec = 5;
      };
    };

    environment.systemPackages = with pkgs; [
      xdotool
      libnotify
    ];

    # Set as default file manager via xdg-mime
    environment.etc."xdg/archivist.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Archivist
      Exec=${pkgs.python3}/bin/python3 -m archivist
      MimeType=inode/directory;
    '';
  };
}
