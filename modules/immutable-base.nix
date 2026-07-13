{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix.immutable-base;
  fauxnix-wallpaper = ../assets/wallpapers/Fauxnix_native.png;
  fennix-extension = ../modules/gnome/fennix-extension;
  nexus-welcome-script = ../scripts/nexus-welcome.sh;
  nexus-welcome-desktop = ../modules/gnome/nexus-welcome.desktop;
  nexus-search-provider = ../scripts/nexus-search-provider.py;
  nexus-search-desktop = ../modules/gnome/nexus-search-provider.desktop;
  nexus-search-ini = ../modules/gnome/org.fauxnix.NexusSearchProvider.search-provider.ini;
in
{
  options.fauxnix.immutable-base = {
    enable = lib.mkEnableOption "Immutable FauxnixOS base — read-only root, GNOME desktop, Nexus daemon. All work in threads.";

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable GNOME desktop on the base system";
    };

    persistentPaths = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "/home"
        "/var/lib/workspaces"
        "/var/lib/workspaces-shared"
        "/var/lib/ollama"
        "/var/lib/systemd"
        "/var/log"
      ];
      description = "Paths persisting across reboots (btrfs subvolumes)";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.initrd.systemd.enable = true;

    # Immutable root
    fileSystems."/" = {
      device = "tmpfs";
      fsType = "tmpfs";
      options = [ "defaults" "size=6G" "mode=755" ];
    };

    fileSystems."/nix" = lib.mkIf (!config.boot.isContainer) {
      device = "/dev/disk/by-label/NIXROOT";
      fsType = "btrfs";
      options = [ "subvol=@nix" "ro" "noatime" ];
      neededForBoot = true;
    };

    fileSystems."/boot" = lib.mkIf (!config.boot.isContainer) {
      device = "/dev/disk/by-label/ESP";
      fsType = "vfat";
      options = [ "noatime" ];
    };

    boot.initrd.supportedFilesystems = [ "btrfs" "vfat" ];

    # Core services
    services.openssh = {
      enable = true;
      settings.PermitRootLogin = lib.mkForce "no";
      settings.PasswordAuthentication = lib.mkForce false;
    };

    services.ollama.enable = true;

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
          "PYTHONPATH=/fauxnix-core/packages/nexus:/fauxnix-core/packages/fauxnix-tools"
        ];
      };
    };

    # GNOME Desktop
    services.xserver = lib.mkIf cfg.enableDesktop {
      enable = true;
      videoDrivers = [ "modesetting" ];
      xkb = {
        layout = "us";
        options = "caps:escape";
      };
    };

    services.displayManager.gdm = lib.mkIf cfg.enableDesktop {
      enable = true;
    };

    services.desktopManager.gnome = lib.mkIf cfg.enableDesktop {
      enable = true;
    };

    services.pipewire = lib.mkIf cfg.enableDesktop {
      enable = true;
      pulse.enable = true;
      alsa.enable = true;
      alsa.support32Bit = true;
    };

    # Fennix GNOME extension
    environment.etc."skel/.local/share/gnome-shell/extensions/fennix@fauxnix.local".source = fennix-extension;

    programs.dconf.profiles.gdm.databases = lib.mkIf cfg.enableDesktop [
      {
        settings = {
          "org/gnome/desktop/background" = {
            picture-uri = "file://${fauxnix-wallpaper}";
            picture-uri-dark = "file://${fauxnix-wallpaper}";
            picture-options = "zoom";
            primary-color = "#000000";
          };
          "org/gnome/desktop/screensaver" = {
            picture-uri = "file://${fauxnix-wallpaper}";
            picture-options = "zoom";
          };
          "org/gnome/shell" = {
            enabled-extensions = [ "fennix@fauxnix.local" ];
            favorite-apps = [ "org.gnome.Console.desktop" "org.gnome.Nautilus.desktop" ];
          };
        };
      }
    ];

    # Nexus welcome dialog — first-boot assistant
    environment.etc."xdg/autostart/nexus-welcome.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Nexus Welcome
      Comment=Pick up where you left off
      Exec=/run/current-system/sw/bin/nexus-welcome
      Terminal=false
      NoDisplay=true
      X-GNOME-Autostart-enabled=true
      X-GNOME-Autostart-Delay=3
    '';
    environment.systemPackages = with pkgs; [
      git
      btrfs-progs
      python3
      curl
      htop
      waypipe
      zenity
      python3
      python3.pkgs.pygobject3
    ] ++ lib.optionals cfg.enableDesktop [
      gnome-console
      gnome-text-editor
      nautilus
      gnome-shell-extensions
    ];

    environment.variables.PATH = [ "$HOME/.local/bin" ];

    # Hardening
    boot.kernel.sysctl."kernel.modules_disabled" = lib.mkDefault 1;
    security.sudo.execWheelOnly = true;
    users.users.root.initialPassword = lib.mkForce "!";

    networking.firewall.allowedTCPPorts = [ 22 ]
      ++ lib.optionals cfg.enableDesktop (lib.range 5900 5920);

    # Runtime directories + welcome script
    system.activationScripts.fauxnixDirs = ''
      mkdir -p /run/nexus
      chmod 755 /run/nexus
      for path in ${lib.concatStringsSep " " cfg.persistentPaths}; do
        mkdir -p "$path"
      done
      mkdir -p /etc/nixos
      mkdir -p /var/lib/nixos
      cp ${nexus-welcome-script} /run/current-system/sw/bin/nexus-welcome
      chmod +x /run/current-system/sw/bin/nexus-welcome
      cp ${nexus-search-provider} /run/current-system/sw/bin/nexus-search-provider
      chmod +x /run/current-system/sw/bin/nexus-search-provider
    '';

    # Nexus search provider
    environment.etc."xdg/autostart/nexus-search-provider.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Nexus Search
      Exec=/run/current-system/sw/bin/nexus-search-provider
      Terminal=false
      NoDisplay=true
      X-GNOME-Autostart-enabled=true
    '';

    environment.etc."skel/.local/share/gnome-shell/search-providers/org.fauxnix.NexusSearchProvider.search-provider.ini".text = ''
      [Shell Search Provider]
      DesktopId=nexus-search-provider.desktop
      BusName=org.fauxnix.NexusSearchProvider
      ObjectPath=/org/fauxnix/NexusSearchProvider
      Version=2
    '';

    system.stateVersion = "26.05";
  };
}
