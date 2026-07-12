{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix.fennix;

  fauxnix-tools = pkgs.python3.pkgs.buildPythonPackage {
    pname = "fauxnix-tools";
    version = "0.1.0";
    format = "pyproject";
    src = /home/chxk/Projects/fauxnix-core/packages/fauxnix-tools;
    nativeBuildInputs = with pkgs.python3.pkgs; [ setuptools ];
    propagatedBuildInputs = with pkgs.python3.pkgs; [
      ollama chromadb pillow pytesseract pymupdf
      python-docx openpyxl opencv4 numpy requests
      faster-whisper
    ];
    pythonRemoveDeps = [ "opencv-python-headless" "chromadb" ];
    pythonRelaxDeps = true;
    doCheck = false;
  };

  fennix = pkgs.python3.pkgs.buildPythonPackage {
    pname = "fennix";
    version = "0.1.0";
    format = "pyproject";
    src = /home/chxk/Projects/fauxnix-core/packages/fennix;
    nativeBuildInputs = with pkgs.python3.pkgs; [ setuptools ];
    propagatedBuildInputs = with pkgs.python3.pkgs; [
      fauxnix-tools pyperclip psutil
      pyqt6
    ];
    pythonRelaxDeps = true;
    doCheck = false;
  };

  fennix-python = pkgs.python3.withPackages (ps: [ fennix ]);
in
{
  options.fauxnix.fennix = {
    enable = lib.mkEnableOption "Fennix — OS-integrated local LLM assistant with context awareness and file ingestion";
    user = lib.mkOption {
      type = lib.types.str;
      default = "chxk";
      description = "User to run Fennix as";
    };
    ingestDirectories = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "~/Documents" "~/Projects" "~/Downloads" ];
      description = "Directories to auto-scan for file ingestion";
    };
    autoIngest = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Automatically ingest files from watched directories";
    };
    clipboardWatch = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Monitor clipboard for context";
    };
    recallTopK = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "Number of recall results to return per query";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.fennix-daemon = {
      description = "Fennix Local LLM Assistant";
      wantedBy = [ "default.target" ];
      after = [ "graphical-session.target" "ollama.service" ];
      partOf = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${fennix-python}/bin/fennix";
        Restart = "always";
        RestartSec = 5;
        Environment = [
          "FENNIX_INGEST_DIRS=${lib.concatStringsSep ":" cfg.ingestDirectories}"
          "FENNIX_AUTO_INGEST=${if cfg.autoIngest then "true" else "false"}"
          "FENNIX_CLIPBOARD_WATCH=${if cfg.clipboardWatch then "true" else "false"}"
          "FENNIX_RECALL_TOPK=${toString cfg.recallTopK}"
        ];
      };
    };

    environment.systemPackages = with pkgs; [
      xdotool
      libnotify
    ];
  };
}
