{ fauxnix, ... }:

let
  inherit (fauxnix.packages) fauxnixArchivistWeb;
in
{
  systemd.services.fauxnix-archivist-web = {
    description = "Fauxnix Archivist browser UI";
    after = [ "network-online.target" "ollama.service" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    environment = {
      ARCHIVIST_HOST = "0.0.0.0";
      ARCHIVIST_PORT = "8776";
      FAUXNIX_ARCHIVIST_DATA = "/home/chvk/.local/share/fauxnix-archivist";
      ARCHIVIST_DATA_DIR = "/home/chvk/.local/share/fauxnix-archivist";
      ARCHIVE_ROOT = "/home/chvk/Archive";
    };
    serviceConfig = {
      ExecStart = "${fauxnixArchivistWeb}/bin/fauxnix-archivist-web";
      Restart = "always";
      RestartSec = "3s";
      User = "chvk";
      Group = "users";
      WorkingDirectory = "/home/chvk";
    };
  };

  networking.firewall.allowedTCPPorts = [ 8776 ];

  environment.etc."fauxnix/archivist-web.env".text = ''
    ARCHIVIST_URL=http://127.0.0.1:8776
    ARCHIVIST_LAN_PORT=8776
    ARCHIVIST_DATA_DIR=/home/chvk/.local/share/fauxnix-archivist
    ARCHIVE_ROOT=/home/chvk/Archive
  '';
}
