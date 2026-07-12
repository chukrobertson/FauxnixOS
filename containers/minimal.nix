{ config, lib, pkgs, ... }:

let
  python-env = pkgs.python3.withPackages (ps: [
    ps.psutil
    ps.pillow
    ps.pytesseract
    ps.pymupdf
    ps.ollama
    ps.opencv4
    ps.numpy
    ps.requests
    ps.pyperclip
  ]);

  fennix-script = pkgs.writeShellScriptBin "fennix-start" ''
    export PATH="${python-env}/bin:$PATH"
    export PYTHONPATH="/fauxnix-core/packages/fennix:/fauxnix-core/packages/fauxnix-tools"
    export FENNIX_AUTO_INGEST=false
    exec ${python-env}/bin/python3 -m fennix
  '';

  archivist-script = pkgs.writeShellScriptBin "archivist-start" ''
    export PATH="${python-env}/bin:$PATH"
    export PYTHONPATH="/fauxnix-core/packages/archivist:/fauxnix-core/packages/fauxnix-tools"
    export ARCHIVIST_AUTO_ORGANIZE=true
    export ARCHIVIST_AUTO_CLASSIFY=true

    ${python-env}/bin/python3 -c "
import sys, os, signal, time
sys.path.insert(0, '/fauxnix-core/packages/archivist')
sys.path.insert(0, '/fauxnix-core/packages/fauxnix-tools')

from archivist.db import init_archivist_db
from archivist.file_manager.daemon import ArchivistDaemon, add_watched_directory

init_archivist_db()

for path in ['/shared', '/home/chxk']:
    if os.path.isdir(path):
        try:
            add_watched_directory(path)
            print(f'archivist: watching {path}', flush=True)
        except Exception as e:
            print(f'archivist: cannot watch {path} — {e}', flush=True)

daemon = ArchivistDaemon()
daemon.start()
print('archivist: daemon started', flush=True)

running = True
def _shutdown(signum, frame):
    global running
    running = False
signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

while running:
    time.sleep(10)

daemon.stop()
"
  '';
in
{
  boot.isContainer = true;

  networking.useDHCP = false;

  users.users.chxk = {
    isNormalUser = true;
    uid = 1000;
    extraGroups = [ "wheel" ];
    initialPassword = "workspace";
  };

  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "no";
    settings.PasswordAuthentication = true;
    settings.UseDns = false;
  };

  systemd.services.fennix = {
    description = "Fennix In-Thread Assistant";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];
    serviceConfig = {
      Type = "simple";
      ExecStart = "${fennix-script}/bin/fennix-start";
      Restart = "always";
      RestartSec = 5;
      PassEnvironment = "FENNIX_THREAD_NAME";
    };
  };

  systemd.services.archivist = {
    description = "Archivist File Indexer";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" "fennix.service" ];
    serviceConfig = {
      Type = "simple";
      ExecStart = "${archivist-script}/bin/archivist-start";
      Restart = "always";
      RestartSec = 10;
    };
  };

  environment.systemPackages = with pkgs; [
    git
    neovim
    curl
    htop
    btrfs-progs
    python-env
  ];

  system.stateVersion = "26.05";
}
