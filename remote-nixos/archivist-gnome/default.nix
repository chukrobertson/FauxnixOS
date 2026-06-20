{ pkgs ? import <nixpkgs> {}
, archivistAppSrc ? null
}:

let

  archivistPython = pkgs.python3.withPackages (ps: with ps; [
    pygobject3 pycairo
    chromadb ollama pymupdf python-docx openpyxl pillow pytesseract
    faster-whisper opencv-python-headless setuptools
  ]);

  runtimeTools = with pkgs; [ tesseract ffmpeg-headless xdg-utils ];

  # Bundle archivist backend if source provided.
  # We check that the path has at least one .py file so an empty copy doesn't
  # silently produce a broken build.
  hasArchivistSrc = archivistAppSrc != null
    && builtins.pathExists (archivistAppSrc + "/__init__.py");
  archivistLib = if hasArchivistSrc then
    pkgs.stdenvNoCC.mkDerivation {
      pname = "archivist-app-lib";
      version = "0.1.0";
      src = builtins.path {
        path = archivistAppSrc;
        name = "archivist-app-src";
        filter = path: type:
          let base = baseNameOf path;
          in type == "directory" || builtins.match ".*\\.py$" base != null;
      };
      buildPhase = "true";
      installPhase = ''
        mkdir -p $out/lib/archivist_app
        cp -r $src/* $out/lib/archivist_app/
      '';
    }
  else null;

  archivistLibPath = if archivistLib != null
    then "${archivistLib}/lib"
    else "";

  gnomeSrc = builtins.path {
    path = ./.;
    name = "fauxnix-archivist-gnome-src-v1";
    filter = path: type:
      let base = baseNameOf path;
      in type == "directory" || builtins.match ".*\\.py$" base != null;
  };

in

pkgs.stdenv.mkDerivation {
  pname = "fauxnix-archivist";
  version = "0.1.0";
  src = gnomeSrc;
  buildInputs = [ archivistPython ] ++ runtimeTools
    ++ (if archivistLib != null then [ archivistLib ] else []);

  buildPhase = ''
    mkdir -p $out/lib/fauxnix-archivist/archivist_gnome
    cp -r $src/* $out/lib/fauxnix-archivist/archivist_gnome/
    rm -f $out/lib/fauxnix-archivist/archivist_gnome/default.nix
  '';

  installPhase = let
    giPkgs = with pkgs; [
      gtk4 libadwaita glib gdk-pixbuf
      pango.out cairo graphene
      harfbuzz
      gobject-introspection
    ];
    girepos = pkgs.lib.makeSearchPath "lib/girepository-1.0" giPkgs;
  in ''
    mkdir -p $out/bin
    cat > $out/bin/fauxnix-archivist << 'EOF'
    #!${pkgs.runtimeShell}
    SELF=$(readlink -f "$0")
    SELFDIR=$(dirname "$SELF")
    ARCHLIBDIR=$(dirname "$SELFDIR")
    export GI_TYPELIB_PATH="${girepos}"
    export GDK_PIXBUF_MODULE_FILE="${pkgs.librsvg}/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
    export PATH="${pkgs.lib.makeBinPath runtimeTools}:$PATH"
    archivist_lib="${archivistLibPath}"
    if [ -n "$archivist_lib" ]; then
      export PYTHONPATH="$ARCHLIBDIR/lib/fauxnix-archivist:$archivist_lib''${PYTHONPATH:+:$PYTHONPATH}"
      export ARCHIVIST_SRC="$archivist_lib/archivist_app"
    else
      export PYTHONPATH="$ARCHLIBDIR/lib/fauxnix-archivist''${PYTHONPATH:+:$PYTHONPATH}"
    fi
    export TESSERACT_CMD="${pkgs.tesseract}/bin/tesseract"
    LOGFILE="/tmp/fauxnix-archivist-$$.log"
    echo "[$(date)] Starting with DISPLAY=$DISPLAY WAYLAND_DISPLAY=$WAYLAND_DISPLAY" >> "$LOGFILE"
    ${archivistPython}/bin/python3 -m archivist_gnome "$@" >> "$LOGFILE" 2>&1
    rc=$?
    echo "[$(date)] Exited with code $rc" >> "$LOGFILE"
    exit $rc
    EOF
    chmod +x $out/bin/fauxnix-archivist

    mkdir -p $out/share/applications
    cat > $out/share/applications/fauxnix-archivist.desktop << EOF2
    [Desktop Entry]
    Type=Application
    Name=Fauxnix Archivist
    Comment=Semantic file manager with AI-powered search
    Exec=$out/bin/fauxnix-archivist
    Icon=org.fauxnix.Archivist
    Terminal=false
    Categories=GNOME;GTK;FileManager;Utility;
    MimeType=inode/directory;
    EOF2
  '';

  meta = with pkgs.lib; {
    description = "GNOME file manager with semantic search, OCR, transcription, and archive management";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
