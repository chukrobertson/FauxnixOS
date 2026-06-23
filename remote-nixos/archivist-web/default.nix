{ pkgs ? import <nixpkgs> {}
, archivistAppSrc ? ../archivist_app
, archivistWebSrc ? ../archivist_web
}:

let
  archivistPython = pkgs.python3.withPackages (ps: with ps; [
    fastapi
    uvicorn
    python-multipart
    aiofiles
    pydantic
    ollama
    chromadb
    pymupdf
    python-docx
    openpyxl
    pillow
    pytesseract
    watchdog
    opencv-python-headless
    faster-whisper
    psutil
  ]);

  runtimeTools = with pkgs; [
    ffmpeg-headless
    tesseract
  ];

  appSrc = builtins.path {
    path = archivistAppSrc;
    name = "fauxnix-archivist-app-src";
    filter = path: type:
      let base = baseNameOf path;
      in type == "directory"
        || builtins.match ".*\\.(py|txt|json|md|yaml|yml)$" base != null;
  };

  webSrc = builtins.path {
    path = archivistWebSrc;
    name = "fauxnix-archivist-web-src";
  };
in

pkgs.stdenvNoCC.mkDerivation {
  pname = "fauxnix-archivist-web";
  version = "0.1.0";
  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    app_root="$out/lib/fauxnix-archivist-web"
    mkdir -p "$app_root/app" "$app_root/web" "$out/bin"
    cp -r ${appSrc}/* "$app_root/app/"
    cp -r ${webSrc}/* "$app_root/web/"

    cat > "$out/bin/fauxnix-archivist-web" <<EOF
    #!${pkgs.runtimeShell}
    set -eu
    app_root="$out/lib/fauxnix-archivist-web"
    export PATH="${pkgs.lib.makeBinPath runtimeTools}:\$PATH"
    export PYTHONPATH="\$app_root\''${PYTHONPATH:+:\$PYTHONPATH}"
    export FAUXNIX_ARCHIVIST_DATA="\''${FAUXNIX_ARCHIVIST_DATA:-\$HOME/.local/share/fauxnix-archivist}"
    export ARCHIVIST_DATA_DIR="\''${ARCHIVIST_DATA_DIR:-\$FAUXNIX_ARCHIVIST_DATA}"
    export ARCHIVE_ROOT="\''${ARCHIVE_ROOT:-\$HOME/Archive}"
    export TESSERACT_CMD="${pkgs.tesseract}/bin/tesseract"
    cd "\$app_root"
    exec ${archivistPython}/bin/python3 -m uvicorn app.main:app \\
      --host "\''${ARCHIVIST_HOST:-0.0.0.0}" \\
      --port "\''${ARCHIVIST_PORT:-8776}"
    EOF
    chmod +x "$out/bin/fauxnix-archivist-web"

    runHook postInstall
  '';

  meta = with pkgs.lib; {
    description = "Fauxnix-hosted Archivist FastAPI browser UI";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
