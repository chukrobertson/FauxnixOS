{ python, fauxnix-tools, lib }:

python.pkgs.buildPythonPackage rec {
  pname = "archivist";
  version = "0.1.0";
  format = "pyproject";

  src = ./.;

  nativeBuildInputs = with python.pkgs; [
    setuptools
  ];

  propagatedBuildInputs = with python.pkgs; [
    fauxnix-tools
  ] ++ fauxnix-tools.propagatedBuildInputs;

  doCheck = false;

  pythonImportsCheck = [ "archivist" ];

  meta = with lib; {
    description = "AI-powered intelligent file manager for FauxnixOS";
    license = licenses.mit;
    platforms = platforms.linux;
    mainProgram = "archivist";
  };
}
