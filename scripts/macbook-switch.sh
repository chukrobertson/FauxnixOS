#!/usr/bin/env bash
# Switch MacBook Pro to FauxnixOS
# Creates a boot entry — if it fails, reboot and select previous generation

set -e

CONFIG="/home/chxk/Projects/fauxnix-core/configurations/macbook-fauxnix.nix"
LINK="/etc/nixos/configuration.nix"
BACKUP="/etc/nixos/configuration.nix.bak"

echo "=== FauxnixOS MacBook Integration ==="
echo ""
echo "This will rebuild your NixOS system with FauxnixOS services."
echo "A backup of your current config is saved to: $BACKUP"
echo ""
echo "Safety: If anything goes wrong, reboot and select the"
echo "previous generation in the GRUB boot menu."
echo ""

if [ "$1" = "--test" ]; then
    echo "Running TEST build (changes not saved to bootloader)..."
    sudo cp "$CONFIG" "$LINK"
    sudo nixos-rebuild test -I nixos-config="$CONFIG"
    sudo cp "$BACKUP" "$LINK"
    echo ""
    echo "Test complete. System reverted to previous config."
    echo "To make permanent: $0 --switch"
elif [ "$1" = "--switch" ]; then
    echo "Making permanent switch..."
    sudo cp "$LINK" "$BACKUP"
    sudo cp "$CONFIG" "$LINK"
    sudo nixos-rebuild switch -I nixos-config="$LINK"
    echo ""
    echo "FauxnixOS is now active!"
    echo "Reboot to complete the switch."
    echo "Nexus daemon will auto-start on next boot."
else
    echo "Usage:"
    echo "  $0 --test    Test the build (temporary, reverts after)"
    echo "  $0 --switch  Make permanent (with bootloader fallback)"
    echo ""
    echo "Recommended: run --test first to verify everything builds."
fi
