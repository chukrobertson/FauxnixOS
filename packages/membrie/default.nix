{ python, fauxnix-tools, lib }:

python.pkgs.buildPythonPackage rec {
  pname = "membrie";
  version = "3.0.0";
  format = "pyproject";

  src = ./.;

  nativeBuildInputs = with python.pkgs; [
    setuptools
  ];

  propagatedBuildInputs = with python.pkgs; [
    fauxnix-tools
    fastapi
    uvicorn
    python-multipart
    aiofiles
    pyperclip
  ] ++ fauxnix-tools.propagatedBuildInputs;

  doCheck = false;

  pythonImportsCheck = [ "membrie" ];

  meta = with lib; {
    description = "AI-powered session tracking and memory companion for FauxnixOS";
    license = licenses.mit;
    platforms = platforms.linux;
    mainProgram = "membrie";
  };
}
