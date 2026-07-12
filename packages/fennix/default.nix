{ python, fauxnix-tools, lib }:

python.pkgs.buildPythonPackage rec {
  pname = "fennix";
  version = "0.1.0";
  format = "pyproject";

  src = ./.;

  nativeBuildInputs = with python.pkgs; [
    setuptools
  ];

  propagatedBuildInputs = with python.pkgs; [
    fauxnix-tools
    pyperclip
    psutil
  ] ++ fauxnix-tools.propagatedBuildInputs;

  doCheck = false;

  pythonImportsCheck = [ "fennix" ];

  meta = with lib; {
    description = "OS-integrated local LLM assistant for FauxnixOS";
    license = licenses.mit;
    platforms = platforms.linux;
    mainProgram = "fennix";
  };
}
