# FauxnixOS — MacBook Pro integration config
# Adds FauxnixOS services (Nexus, threads, GNOME extension, wsctl)
# WITHOUT replacing the disk layout. Existing system stays intact.
# Safe to test: nixos-rebuild test (temporary) or switch (persistent with fallback)

{ config, lib, pkgs, ... }:

{
  imports = [
    /etc/nixos/hardware-configuration.nix
    /etc/nixos/modules/boot.nix
    /etc/nixos/modules/desktop.nix
    /etc/nixos/modules/networking.nix
    /etc/nixos/modules/services.nix
    /etc/nixos/modules/storage.nix
    /etc/nixos/modules/packages.nix
    /etc/nixos/modules/users.nix
    /etc/nixos/modules/nix-config.nix
    /etc/nixos/modules/systemd-extra.nix
    /home/chxk/Projects/fauxnix-core/modules/fennix.nix
    /home/chxk/Projects/fauxnix-core/modules/immutable-base.nix
  ];

  # FauxnixOS settings
  fauxnix = {
    immutable-base.enable = lib.mkForce false;
    immutable-base.enableDesktop = true;
    fennix.enable = true;
  };

  networking.hostName = "fauxbookpro";
  time.timeZone = "America/Kentucky/Louisville";

  i18n.defaultLocale = "en_US.UTF-8";
  i18n.extraLocaleSettings = {
    LC_ADDRESS = "en_US.UTF-8";
    LC_IDENTIFICATION = "en_US.UTF-8";
    LC_MEASUREMENT = "en_US.UTF-8";
    LC_MONETARY = "en_US.UTF-8";
    LC_NAME = "en_US.UTF-8";
    LC_NUMERIC = "en_US.UTF-8";
    LC_PAPER = "en_US.UTF-8";
    LC_TELEPHONE = "en_US.UTF-8";
    LC_TIME = "en_US.UTF-8";
  };

  # FauxnixOS workspace infrastructure
  system.activationScripts.fauxnixSetup = ''
    mkdir -p /var/lib/workspaces
    mkdir -p /var/lib/workspaces-shared
    mkdir -p /var/lib/workspaces/.snapshots
    mkdir -p /run/nexus
    chmod 755 /run/nexus

    if [ ! -d /var/lib/workspaces/.template ]; then
      echo "[fauxnix] template not found — run 'wsctl setup' to create"
    fi
  '';

  # Add wsctl to system path
  environment.systemPackages = with pkgs; [
    zenity
    python3
    python3.pkgs.pygobject3
  ];

  environment.variables.PATH = [ "$HOME/.local/bin" ];

  # GNOME Fennix extension
  environment.etc."skel/.local/share/gnome-shell/extensions/fennix@fauxnix.local".source =
    /home/chxk/Projects/fauxnix-core/modules/gnome/fennix-extension;

  # Nexus welcome autostart
  environment.etc."xdg/autostart/nexus-welcome.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Nexus Welcome
    Exec=/home/chxk/.local/bin/wsctl status demo 2>/dev/null; /home/chxk/Projects/fauxnix-core/scripts/nexus-welcome.sh
    Terminal=false
    NoDisplay=true
    X-GNOME-Autostart-enabled=true
    X-GNOME-Autostart-Delay=3
  '';

  # Nexus search provider autostart
  environment.etc."xdg/autostart/nexus-search.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Nexus Search
    Exec=${pkgs.python3}/bin/python3 /home/chxk/Projects/fauxnix-core/scripts/nexus-search-provider.py
    Terminal=false
    NoDisplay=true
    X-GNOME-Autostart-enabled=true
  '';

  # Search provider registration
  environment.etc."skel/.local/share/gnome-shell/search-providers/org.fauxnix.NexusSearchProvider.search-provider.ini".text = ''
    [Shell Search Provider]
    DesktopId=nexus-search.desktop
    BusName=org.fauxnix.NexusSearchProvider
    ObjectPath=/org/fauxnix/NexusSearchProvider
    Version=2
  '';

  # Fennix extension enabled
  programs.dconf.profiles.gdm.databases = [
    {
      settings = {
        "org/gnome/shell" = {
          enabled-extensions = [ "fennix@fauxnix.local" ];
        };
      };
    }
  ];

  # Nexus daemon
  systemd.services.nexus = {
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

  # Ollama (if not already enabled)
  services.ollama.enable = true;

  system.stateVersion = "26.05";
}
