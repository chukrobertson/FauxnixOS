{ pkgs, lib, fauxnix, ... }:

let
  inherit (fauxnix.paths) cowriterWorkspace;
  inherit (fauxnix.packages)
    fennixChatLauncher
    fennixDesktop
    fennixPython
    fauxd
    fauxdex
    fennixCode
    fauxfetch
    fauxnixFetch
    fauxnixGit
    fauxnixCanvas
    fauxnixNode
    fauxnixNodeDesktop
    fauxnixRofi
    fauxnixThreadLauncher
    fauxPass
    fauxnixScreenshot
    fauxnixSettings
    fauxnixSddmTheme
    fauxnixWallDisplay
    fauxnixArchivist
    fauxnixArchivistWeb
    ;
in
{
  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
    alacritty
    brightnessctl
    curl
    ethtool
    fennixChatLauncher
    fennixDesktop
    fennixPython
    fauxd
    fauxdex
    fennixCode
    fauxfetch
    fauxnixFetch
    fauxnixGit
    fauxnixCanvas
    fauxnixNode
    fauxnixNodeDesktop
    fauxnixRofi
    fauxnixThreadLauncher
    fauxPass
    fauxnixScreenshot
    fauxnixSettings
    fauxnixSddmTheme
    fauxnixWallDisplay
    fauxnixArchivistWeb
    git
    iw
    jq
    mesa-demos
    pciutils
    pavucontrol
    qemu_full
    ripgrep
    rsync
    swtpm
    usbutils
    OVMF.fd
    wayfire
    waybar
    wl-clipboard
    wlrctl
    xwayland
    # Application suite
    gimp
    krita
    vscodium
    chromium
    amberol
    libreoffice
  ]
  ++ lib.optionals (builtins.hasAttr "gnome-tweaks" pkgs) [
    pkgs.gnome-tweaks
  ]
  ++ lib.optionals (builtins.hasAttr "gnome-extension-manager" pkgs) [
    pkgs.gnome-extension-manager
  ]
  ++ lib.optionals (builtins.hasAttr "whitesur-gtk-theme" pkgs) [
    pkgs.whitesur-gtk-theme
  ]
  ++ lib.optionals (builtins.hasAttr "whitesur-icon-theme" pkgs) [
    pkgs.whitesur-icon-theme
  ]
  ++ lib.optionals (builtins.hasAttr "bibata-cursors" pkgs) [
    pkgs.bibata-cursors
  ]
  ++ lib.optionals (builtins.hasAttr "appindicator" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.appindicator
  ]
  ++ lib.optionals (builtins.hasAttr "blur-my-shell" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.blur-my-shell
  ]
  ++ lib.optionals (builtins.hasAttr "dash-to-dock" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.dash-to-dock
  ]
  ++ lib.optionals (builtins.hasAttr "just-perfection" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.just-perfection
  ]
  ++ lib.optionals (builtins.hasAttr "user-themes" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.user-themes
  ]
  ++ [
    (writeShellApplication {
      name = "fennix";
      runtimeInputs = [ fennixPython ];
      text = ''
        set -eu

        mode=local
        if [ "$#" -gt 0 ] && { [ "$1" = "--parent" ] || [ "$1" = "-p" ]; }; then
          mode=parent
          shift
        fi

        exec ${fennixPython}/bin/python3 /etc/fennix/gui.py --route "$mode" --ask "$@"
      '';
    })
    (writeShellApplication {
      name = "fauxnix-assistant";
      runtimeInputs = [ ];
      text = ''
        exec fennix "$@"
      '';
    })
    (writeShellApplication {
      name = "fennix-gui";
      runtimeInputs = [ fennixPython ];
      text = ''
        exec python3 /etc/fennix/gui.py "$@"
      '';
    })
    (writeShellApplication {
      name = "cowriter";
      runtimeInputs = [ fennixPython ];
      text = ''
        export FAUXNIX_COWRITER_WORKSPACE=''${FAUXNIX_COWRITER_WORKSPACE:-${cowriterWorkspace}}
        exec python3 /etc/fennix/cowriter.py "$@"
      '';
    })
    fauxnixArchivist
  # vim # Do not forget to add an editor to edit configuration.nix! The Nano editor is also installed by default.
  # wget
  ];
}
