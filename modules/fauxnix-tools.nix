{ config, lib, pkgs, ... }:

let
  cfg = config.fauxnix;
  fauxnix-tools = pkgs.python3Packages.fauxnix-tools or pkgs.python3.pkgs.buildPythonPackage {
    pname = "fauxnix-tools";
    version = "0.1.0";
    format = "pyproject";
    src = builtins.path { path = ../../packages/fauxnix-tools; };
    nativeBuildInputs = with pkgs.python3.pkgs; [ setuptools ];
    propagatedBuildInputs = with pkgs.python3.pkgs; [
      ollama chromadb pillow pytesseract pymupdf
      python-docx openpyxl opencv4 numpy requests
    ];
    doCheck = false;
  };
in
{
  options.fauxnix = {
    enable = lib.mkEnableOption "Fauxnix shared AI tooling";
    dataDir = lib.mkOption {
      type = lib.types.str;
      default = "${config.users.users.${cfg.user}.home}/.local/share/fauxnix";
      description = "Data directory for Fauxnix tools";
    };
    user = lib.mkOption {
      type = lib.types.str;
      default = "fauxnix";
      description = "User to run Fauxnix tools as";
    };
    ollamaHost = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:11434";
      description = "Ollama API host";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      fauxnix-tools
      pkgs.tesseract
      pkgs.ffmpeg
    ];

    environment.variables = {
      FAUXNIX_DATA_DIR = cfg.dataDir;
      FAUXNIX_OLLAMA_HOST = cfg.ollamaHost;
      TESSERACT_CMD = "${pkgs.tesseract}/bin/tesseract";
    };

    services.ollama = {
      enable = true;
      acceleration = lib.mkDefault null;
    };
  };
}
