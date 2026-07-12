{ python, lib }:

python.pkgs.buildPythonPackage rec {
  pname = "fauxnix-tools";
  version = "0.1.0";
  format = "pyproject";

  src = ./.;

  nativeBuildInputs = with python.pkgs; [
    setuptools
  ];

  propagatedBuildInputs = with python.pkgs; [
    ollama
    chromadb
    pillow
    pytesseract
    pymupdf
    python-docx
    openpyxl
    opencv4
    numpy
    requests
    faster-whisper
  ];

  pythonRemoveDeps = [ "opencv-python-headless" "chromadb" ];
  pythonRelaxDeps = true;

  doCheck = false;

  meta = with lib; {
    description = "Shared AI tooling for FauxnixOS";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
