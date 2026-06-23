{ lib, fauxnix, ... }:

let
  inherit (fauxnix.packages) fauxnixAdminAgent;
in
{
  systemd.services.fauxnix-admin-agent = {
    description = "Fauxnix Admin Agent — LLM-based system management agent";
    after = [ "network-online.target" "ollama.service" ];
    wants = [ "network-online.target" "ollama.service" ];
    wantedBy = [ "multi-user.target" ];
    environment = {
      FAUXNIX_ADMIN_AGENT_HOST = "127.0.0.1";
      FAUXNIX_ADMIN_AGENT_PORT = "8757";
      FAUXNIX_LLM_BACKEND = "ollama";
      FAUXNIX_LLM_MODEL = "qwen2.5:0.5b-instruct";
      FAUXNIX_OLLAMA_URL = "http://127.0.0.1:11434";
      FAUXNIX_KB_DIR = "/home/chvk/.config/fauxnix/kb";
      PATH = lib.mkForce "/run/wrappers/bin:/run/current-system/sw/bin:/usr/bin";
    };
    serviceConfig = {
      ExecStart = "${fauxnixAdminAgent}/bin/fauxnix-admin-agent --host 127.0.0.1 --port 8757";
      Restart = "on-failure";
      RestartSec = "5s";
      User = "chvk";
      Group = "users";
    };
  };

  networking.firewall.allowedTCPPorts = [ 8757 ];
}
