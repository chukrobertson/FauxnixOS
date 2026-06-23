{ fauxnix, ... }:

let
  inherit (fauxnix.packages) fauxnixWallDisplay;
in
{
  systemd.services.fauxnix-wall-display = {
    description = "Fauxnix Wall Display — family calendar kiosk UI";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    environment = {
      FAUXNIX_WALL_HOST = "0.0.0.0";
      FAUXNIX_WALL_PORT = "8780";
      FAUXNIX_WALL_CALENDAR = "/home/chvk/.config/fauxnix/wall-calendar.json";
    };
    serviceConfig = {
      ExecStart = "${fauxnixWallDisplay}/bin/fauxnix-wall-display --host 0.0.0.0 --port 8780";
      Restart = "always";
      RestartSec = "2s";
      User = "chvk";
      Group = "users";
      WorkingDirectory = "/home/chvk";
    };
  };

  networking.firewall.allowedTCPPorts = [ 8780 ];

  environment.etc."fauxnix/wall-display.env".text = ''
    FAUXNIX_WALL_URL=http://127.0.0.1:8780
    FAUXNIX_WALL_LAN_PORT=8780
  '';
}
