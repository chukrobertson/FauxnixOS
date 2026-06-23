{ pkgs, ... }:

{
  # Fauxnix Wayfire workspace profile. SDDM auto-login starts Wayfire, and
  # Wayfire autostarts the PyQt workspace through ./wayfire.nix.
  services.xserver.enable = true;
  services.displayManager.gdm = {
    enable = false;
  };
  services.desktopManager.gnome.enable = false;
  services.displayManager.sddm = {
    enable = true;
    wayland.enable = false;
    theme = "fauxnix-login-v2";
    settings.General.GreeterEnvironment = "QML_DISABLE_DISK_CACHE=1";
    settings.Theme = {
      Current = "fauxnix-login-v2";
      ThemeDir = "/run/current-system/sw/share/sddm/themes";
    };
    settings.Autologin = {
      User = "chvk";
      Session = "wayfire";
    };
  };
  environment.etc."sddm.conf.d/fauxnix-theme.conf".text = ''
    [General]
    GreeterEnvironment=QML_DISABLE_DISK_CACHE=1

    [Theme]
    Current=fauxnix-login-v2
    ThemeDir=/run/current-system/sw/share/sddm/themes

    [Autologin]
    User=chvk
    Session=wayfire
  '';
  services.displayManager.defaultSession = "wayfire";
  services.displayManager.autoLogin = {
    enable = true;
    user = "chvk";
  };

  xdg.portal = {
    enable = true;
    config.common.default = "*";
    extraPortals = with pkgs; [
      xdg-desktop-portal-gtk
      xdg-desktop-portal-wlr
    ];
  };

  # Configure keymap in X11
  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };
}
