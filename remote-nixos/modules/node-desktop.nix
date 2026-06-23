{ lib, fauxnix, ... }:

let
  inherit (fauxnix.packages) fauxnixNodeDesktop;
in
{
  systemd.services.fauxnix-node-desktop = {
    description = "Fauxnix browser desktop and LAN status UI";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    environment = {
      FAUXNIX_NODE_DESKTOP_HOST = "0.0.0.0";
      FAUXNIX_NODE_DESKTOP_PORT = "8765";
      XDG_RUNTIME_DIR = "/run/user/1000";
      WAYLAND_DISPLAY = "wayland-1";
      DISPLAY = ":1";
      NIXOS_OZONE_WL = "1";
      QT_QPA_PLATFORM = "wayland;xcb";
      GDK_BACKEND = "wayland,x11";
      PATH = lib.mkForce "/run/wrappers/bin:/run/current-system/sw/bin:/usr/bin";
    };
    serviceConfig = {
      ExecStart = "${fauxnixNodeDesktop}/bin/fauxnix-node-desktop --host 0.0.0.0 --port 8765";
      Restart = "always";
      RestartSec = "2s";
      User = "chvk";
      Group = "users";
      WorkingDirectory = "/home/chvk/Fauxnix";
    };
  };

  networking.firewall.allowedTCPPorts = [ 8765 ];

  environment.etc."fauxnix/node-desktop.env".text = ''
    FAUXNIX_NODE_DESKTOP_URL=http://127.0.0.1:8765
    FAUXNIX_NODE_DESKTOP_LAN_PORT=8765
  '';
}
