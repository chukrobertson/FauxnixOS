# ── NIXOS CONFIGURATION.NIX SNIPPET ────────────────────────────────────
# Add inside configuration.nix to make the workspace the login desktop.
# This replaces the C fauxshell-host derivation + exec lines.

{ config, pkgs, ... }:

let
  # Build the workspace as a Nix package
  fauxnixWorkspace = pkgs.stdenvNoCC.mkDerivation {
    pname = "fauxnix-workspace";
    version = "0.1.0";

    src = ./fauxnix_workspace;

    buildInputs = [
      (pkgs.python3.withPackages (ps: [ ps.pyqt6 ps.pyqt6-webengine ]))
    ];

    buildPhase = '''';
    installPhase = '''
      mkdir -p $out/lib/fauxnix-workspace
      cp -r fauxnix_workspace/*.py $out/lib/fauxnix-workspace/
      cp -r fauxnix_workspace/nodes $out/lib/fauxnix-workspace/

      mkdir -p $out/bin
      cat > $out/bin/fauxnix-workspace << 'LAUNCHER'
      #!${pkgs.runtimeShell}
      export QT_QPA_PLATFORM=xcb
      export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
      PYTHONPATH="$out/lib/fauxnix-workspace''${PYTHONPATH:+:$PYTHONPATH}"
      exec ${pkgs.python3.withPackages (ps: [ ps.pyqt6 ps.pyqt6-webengine ])}/bin/python3 \
        "$out/lib/fauxnix-workspace/__main__.py" "$@"
      LAUNCHER
      chmod +x $out/bin/fauxnix-workspace
    '';
  };

in
{
  # ── Packages ────────────────────────────────────────────────────────
  environment.systemPackages = with pkgs; [
    python3Packages.pyqt6
    python3Packages.pyqt6-webengine
    fauxnixWorkspace
  ];

  # ── Sway config — replace fauxshell-host with workspace ─────────────
  # Inside your Sway config derivation or activation script, change:
  #
  #   OLD: exec ${fauxshellHost}/bin/fauxshell-host
  #   NEW: exec ${fauxnixWorkspace}/bin/fauxnix-workspace
  #
  #   OLD: exec ${fauxshellHost}/bin/fauxshell-host --launcher
  #   NEW: exec ${fauxnixWorkspace}/bin/fauxnix-workspace --launcher
  #
  #   OLD: bindsym F12 exec ${fauxshellHost}/bin/fauxshell-host --launcher-toggle
  #   NEW: bindsym F12 exec ${fauxnixWorkspace}/bin/fauxnix-workspace --launcher

  # ── Workspace directories ───────────────────────────────────────────
  # Session saves to ~/.config/fauxnix/workspaces/_session.json
  # Created automatically on first run.

  # ── Optional: add to faux-pass registry ─────────────────────────────
  # {
  #   "id": "workspace",
  #   "name": "Workspace Canvas",
  #   "action": ["fauxnix-workspace"]
  # }
}
