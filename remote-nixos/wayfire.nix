{ config, pkgs, lib, fauxnix, ... }:

let
  inherit (fauxnix.packages)
    fauxd
    fauxnixCanvas
    fauxnixRofi
    fauxnixThreadLauncher
    ;

  fauxnixWaybarConfig = pkgs.writeText "waybar-config.jsonc" ''
    {
      "layer": "top",
      "position": "top",
      "height": 30,
      "spacing": 4,
      "modules-left": ["clock"],
      "modules-center": [],
      "modules-right": ["tray"],
      "clock": {
        "format": "{:%H:%M  %a %d %b}",
        "tooltip-format": "<big>{:%Y %B}</big>"
      },
      "tray": { "spacing": 8 }
    }
  '';

  fauxnixWayfireStartup = pkgs.writeShellApplication {
    name = "fauxnix-wayfire-startup";
    runtimeInputs = with pkgs; [ brightnessctl coreutils curl procps xset ];
    text = ''
      LOG="''${XDG_RUNTIME_DIR:-/tmp}/fauxnix-wayfire-startup.log"
      exec >>"$LOG" 2>&1
      set -x
      date "+%Y-%m-%d %H:%M:%S wayfire autostart begin"

      # Wayfire provides the real WAYLAND_DISPLAY/DISPLAY to its children.
      # Do not hardcode them (that was the intermittent-black-screen bug).
      : "''${WAYLAND_DISPLAY:?WAYLAND_DISPLAY is not set}"

      RUNDIR="''${XDG_RUNTIME_DIR:-/run/user/$(id - u)}"
      for _ in $(seq 1 50); do
        [ -S "$RUNDIR/$WAYLAND_DISPLAY" ] && break
        sleep 0.1
      done

      # fauxnix-workspace forces Qt to xcb, so wait for XWayland if needed.
      if [ -n "''${DISPLAY:-}" ]; then
        for _ in $(seq 1 60); do
          ${pkgs.xset}/bin/xset -q >/dev/null 2>&1 && break
          sleep 0.5
        done
      fi

      ${pkgs.brightnessctl}/bin/brightnessctl set 80% 2>/dev/null || true

      # Start daemons. Background jobs do not kill the script on failure.
      if ! pgrep -u "$(id -u)" -f '/etc/fauxshell/fauxd.py' >/dev/null 2>&1; then
        ${pkgs.util-linux}/bin/setsid ${fauxd}/bin/fauxd >/tmp/fauxd-session.log 2>&1 &
      fi

      # The browser desktop is the durable visible surface for the laptop.
      for _ in $(seq 1 80); do
        if ${pkgs.curl}/bin/curl -fsS http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
          break
        fi
        sleep 0.25
      done

      if ! pgrep -u "$(id -u)" -f 'chromium.*127.0.0.1:8765' >/dev/null 2>&1; then
        chromium_profile="$HOME/.local/share/fauxnix-admin-panel/chromium-kiosk"
        mkdir -p "$chromium_profile"
        ${pkgs.util-linux}/bin/setsid ${pkgs.chromium}/bin/chromium \
          --ozone-platform=wayland \
          --enable-features=UseOzonePlatform \
          --kiosk \
          --no-first-run \
          --no-default-browser-check \
          --disable-session-crashed-bubble \
          --password-store=basic \
          --user-data-dir="$chromium_profile" \
          http://127.0.0.1:8765 >/tmp/fauxnix-admin-panel-kiosk.log 2>&1 &
      fi

      if [ "''${FAUXNIX_AUTOSTART_WORKSPACE:-0}" != "1" ]; then
        echo "fauxnix-workspace autostart disabled; set FAUXNIX_AUTOSTART_WORKSPACE=1 to restore the PyQt workspace watchdog."
        while true; do
          sleep 3600
        done
      fi

      # Workspace watchdog: never let a single startup crash kill the session.
      attempt=0
      max_backoff=30
      while true; do
        attempt=$((attempt + 1))
        echo "Starting fauxnix-workspace (attempt $attempt)..."
        if ${fauxnixCanvas}/bin/fauxnix-workspace; then
          attempt=0
        else
          code=$?
          echo "fauxnix-workspace exited with code $code"
        fi
        backoff=$((attempt > max_backoff ? max_backoff : attempt))
        sleep "$backoff"
      done
    '';
  };

  fauxnixWayfireConfig = pkgs.writeText "wayfire.ini" ''
    [core]
    plugins = alpha autostart command cube expo fast-switcher foreign-toplevel grid invert ipc move oswitch place resize switcher stipc vswitch window-rules wm-actions wrot zoom
    close_top_view = <super> KEY_Q
    vwidth = 6
    vheight = 1

    [autostart]
    # Key name must differ from the option name "autostart" to be parsed
    # correctly by Wayfire 0.10's compound-list handler.
    fauxnix_desktop = ${fauxnixWayfireStartup}/bin/fauxnix-wayfire-startup

    [command]
    # Wayfire 0.10 splits binding and command into separate keys.
    binding_terminal = <super> KEY_ENTER
    command_terminal = ${pkgs.alacritty}/bin/alacritty

    binding_launcher = <super> KEY_D
    command_launcher = ${fauxnixRofi}/bin/rofi -show drun

    binding_threadmenu = <super> KEY_T
    command_threadmenu = ${fauxnixThreadLauncher}/bin/fauxnix-thread menu

    binding_fennix = <super> KEY_F
    command_fennix = ${fauxnixThreadLauncher}/bin/fauxnix-thread fennix

    binding_fauxnix_thread = <super> <shift> KEY_F
    command_fauxnix_thread = ${fauxnixThreadLauncher}/bin/fauxnix-thread fauxnix

    binding_cowriter = <super> <shift> KEY_C
    command_cowriter = ${fauxnixThreadLauncher}/bin/fauxnix-thread cowriter

    binding_canvas_return = <super> KEY_ESCAPE
    command_canvas_return = ${pkgs.wayfire}/bin/wf-msg expo

    binding_close_return = <super> <shift> KEY_ESCAPE
    command_close_return = ${pkgs.util-linux}/bin/kill -9 $(${pkgs.procps}/bin/pidof foot firefox chromium gimp 2>/dev/null | tr ' ' '\n' | head -1); ${pkgs.wayfire}/bin/wf-msg expo

    [input]
    tap_to_click = true
    natural_scroll = true
    disable_touchpad_while_typing = true

    [output]
    mode = 1600x900@60

    [vswitch]
    binding_left = <super> <ctrl> KEY_LEFT
    binding_right = <super> <ctrl> KEY_RIGHT
    binding_up = <super> <ctrl> KEY_UP
    binding_down = <super> <ctrl> KEY_DOWN

    [expo]
    select_workspace_1 = KEY_1
    select_workspace_2 = KEY_2
    select_workspace_3 = KEY_3
    select_workspace_4 = KEY_4
    select_workspace_5 = KEY_5
    select_workspace_6 = KEY_6

    [grid]
    slot_bl = <super> KEY_KP1
    slot_b = <super> KEY_KP2
    slot_br = <super> KEY_KP3
    slot_l = <super> KEY_KP4
    slot_c = <super> KEY_KP5
    slot_r = <super> KEY_KP6
    slot_tl = <super> KEY_KP7
    slot_t = <super> KEY_KP8
    slot_tr = <super> KEY_KP9

    [move]
    activate = <super> BTN_LEFT

    [resize]
    activate = <super> BTN_RIGHT

    [wm-actions]
    toggle_fullscreen = <super> KEY_M
    toggle_sticky = <super> <shift> KEY_S
  '';

  fauxnixWayfireSession = pkgs.stdenvNoCC.mkDerivation {
    pname = "fauxnix-wayfire-session";
    version = "0.1.0";
    dontUnpack = true;
    installPhase = ''
      mkdir -p $out/share/wayland-sessions $out/bin
      cat > $out/bin/fauxnix-wayfire-launch << 'EOF'
      #!/nix/store/gik3rh1vz2jlgnifb9dh6vc6sxwwz9jj-bash-5.3p9/bin/bash
      rm -f /tmp/wayfire-debug.log
      # Force Wayfire to treat /etc/wayfire/defaults.ini as the active user
      # config so that dynamic-list options (autostart, command, window-rules)
      # are parsed correctly. Without this, options from the system defaults
      # file are treated as plain defaults and compound-list entries are ignored.
      export WAYFIRE_CONFIG_FILE=/etc/wayfire/defaults.ini
      exec ${pkgs.wayfire}/bin/wayfire -d >> /tmp/wayfire-debug.log 2>&1
      EOF
      chmod +x $out/bin/fauxnix-wayfire-launch
      cat > $out/share/wayland-sessions/wayfire.desktop << EOF
      [Desktop Entry]
      Name=Wayfire
      Comment=3D Wayland compositor
      Exec=$out/bin/fauxnix-wayfire-launch
      Type=Application
      EOF
    '';
    passthru.providedSessions = [ "wayfire" ];
  };
in
{
  nixpkgs.overlays = [
    (final: prev: {
      wf-config = prev.wf-config.overrideAttrs (old: {
        doCheck = false;
        mesonFlags = [ "-Dtests=disabled" ];
        nativeCheckInputs = [];
        checkInputs = [];
      });
      wayfire = prev.wayfire.overrideAttrs (old: {
        doCheck = false;
        mesonFlags = [
          "--sysconfdir /etc"
          "-Duse_system_wlroots=enabled"
          "-Duse_system_wfconfig=enabled"
          "-Dtests=disabled"
          "-Dwf-touch:tests=disabled"
        ];
        nativeCheckInputs = [];
      });
    })
  ];

  # Wayfire kept as optional session via SDDM picker
  services.displayManager.sessionPackages = [ fauxnixWayfireSession ];
  environment.etc."wayfire/defaults.ini".source = fauxnixWayfireConfig;
  environment.etc."xdg/waybar/config.jsonc".source = fauxnixWaybarConfig;

  environment.systemPackages = with pkgs; [ wlrctl ];
}
