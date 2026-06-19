"""Fauxnix Workspace — Nix derivation for building and installing the workspace canvas."""

{ pkgs ? import <nixpkgs> {} }:

let
  # Collect the Python source tree
  fauxnixWorkspaceSource = builtins.path {
    path = ../.;
    name = "fauxnix-workspace-source";
    filter = path: type:
      let
        base = baseNameOf path;
        ext = if type == "regular" then (builtins.match ".*\\.(.+)" base) else null;
      in
        type == "directory" ||
        (ext != null && builtins.elem (builtins.head ext) ["py"]);
  };

  # Wrap with dependencies
  fauxnixWorkspacePython = pkgs.python3.withPackages (ps: [
    ps.setuptools
    ps.pyqt6
    ps.pyqt6-webengine
  ]);

in

pkgs.stdenv.mkDerivation {
  pname = "fauxnix-workspace";
  version = "0.1.0";

  src = fauxnixWorkspaceSource;

  buildInputs = [ fauxnixWorkspacePython ];

  buildPhase = ''
    mkdir -p $out/lib/fauxnix-workspace
    cp -r fauxnix_workspace $out/lib/fauxnix-workspace/
  '';

  installPhase = ''
    mkdir -p $out/bin
    cat > $out/bin/fauxnix-workspace << 'EOF'
    #!${pkgs.runtimeShell}
    export QT_QPA_PLATFORM=xcb
    export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
    PYTHONPATH="$out/lib/fauxnix-workspace:$PYTHONPATH"
    exec ${fauxnixWorkspacePython}/bin/python3 -m fauxnix_workspace "$@"
    EOF
    chmod +x $out/bin/fauxnix-workspace

    mkdir -p $out/share/applications
    cat > $out/share/applications/fauxnix-workspace.desktop << EOF2
    [Desktop Entry]
    Type=Application
    Name=Fauxnix Workspace
    Comment=Zoomable node-graph desktop canvas
    Exec=$out/bin/fauxnix-workspace
    Icon=fauxnix-workspace
    Terminal=false
    Categories=System;Utility;
    EOF2
  '';

  meta = with pkgs.lib; {
    description = "Zoomable node-graph desktop canvas for FauxnixOS";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
