# Rust development template
{ config, lib, pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    cargo
    rustc
    rust-analyzer
    rustfmt
    clippy
    gcc
    gdb
  ];
}
