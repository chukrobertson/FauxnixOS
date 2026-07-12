{
  description = "FauxnixOS — Nix-based desktop OS with AI-powered memory and file management";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      inherit (flake-utils.lib) eachDefaultSystem;
    in
    {
      nixosModules = {
        fauxnix-tools = import ./modules/fauxnix-tools.nix;
        membrie = import ./modules/membrie.nix;
        archivist = import ./modules/archivist.nix;
        fennix = import ./modules/fennix.nix;
      };

    } // eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3;
        fauxnix-tools = pkgs.callPackage ./packages/fauxnix-tools { inherit python; };
      in
      {
        packages = {
          inherit fauxnix-tools;
          membrie = pkgs.callPackage ./packages/membrie { inherit python fauxnix-tools; };
          archivist = pkgs.callPackage ./packages/archivist { inherit python fauxnix-tools; };
          fennix = pkgs.callPackage ./packages/fennix { inherit python fauxnix-tools; };
        };

        devShells = {
          default = pkgs.mkShell {
            buildInputs = with pkgs; [
              python
              python.pkgs.pip
              python.pkgs.venvShellHook
              fauxnix-tools
            ];
            venvDir = "./.venv";
            postVenvCreation = ''
              unset SOURCE_DATE_EPOCH
              pip install -e ./packages/fauxnix-tools
              pip install -e ./packages/membrie
              pip install -e ./packages/fennix
            '';
          };
          membrie = pkgs.mkShell {
            buildInputs = with pkgs; [
              python
              python.pkgs.pip
              python.pkgs.venvShellHook
              fauxnix-tools
            ];
            venvDir = "./.venv";
            postVenvCreation = ''
              unset SOURCE_DATE_EPOCH
              pip install -e ./packages/fauxnix-tools
              pip install -e ./packages/membrie[full]
            '';
          };
          fennix = pkgs.mkShell {
            buildInputs = with pkgs; [
              python
              python.pkgs.pip
              python.pkgs.venvShellHook
              fauxnix-tools
            ];
            venvDir = "./.venv";
            postVenvCreation = ''
              unset SOURCE_DATE_EPOCH
              pip install -e ./packages/fauxnix-tools
              pip install -e ./packages/fennix[full]
            '';
          };
        };
      });
}
