{ ... }:

{
  services.samba = {
    enable = true;
    nmbd.enable = false;
    winbindd.enable = false;
    openFirewall = false;
    settings = {
      global = {
        "server string" = "Fauxnix Archivist";
        "netbios name" = "FAUXNIX";
        "workgroup" = "WORKGROUP";
        security = "user";
        "map to guest" = "Never";
        "invalid users" = [ "root" ];
        "interfaces" = "lo tailscale0";
        "bind interfaces only" = "no";
        "hosts allow" = "127.0.0.1 100.64.0.0/10";
        "hosts deny" = "0.0.0.0/0";
        "smb ports" = "445";
        "disable netbios" = "yes";
        "server min protocol" = "SMB3_00";
        "server role" = "standalone server";
      };

      Archive = {
        path = "/home/chvk/Archive";
        browseable = "yes";
        "read only" = "no";
        "guest ok" = "no";
        "valid users" = "chvk";
        "force user" = "chvk";
        "force group" = "users";
        "create mask" = "0664";
        "directory mask" = "0775";
      };
    };
  };
}
