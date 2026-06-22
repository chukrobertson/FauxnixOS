#!/usr/bin/env bash
set -euo pipefail

OC_ISO_URL="https://github.com/LongQT-sea/OpenCore-ISO/releases/download/v0.7/LongQT-OpenCore-v0.7.iso"
OC_ISO="LongQT-OpenCore-v0.7.iso"
DISK="macos-disk.qcow2"
DISK_SIZE="80"
DEFAULT_TAILSCALE_IP="100.97.123.113"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

find_first() {
  for path in "$@"; do
    if [ -n "$path" ] && [ -f "$path" ]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

find_glob_first() {
  for pattern in "$@"; do
    # shellcheck disable=SC2086
    for path in $pattern; do
      if [ -f "$path" ]; then
        printf '%s\n' "$path"
        return 0
      fi
    done
  done
  return 1
}

find_ovmf_code() {
  find_first \
    "${FAUXNIX_OVMF_CODE:-}" \
    /run/current-system/sw/share/OVMF/OVMF_CODE.fd \
    /run/current-system/sw/FV/OVMF_CODE.fd \
    /usr/share/OVMF/OVMF_CODE.fd \
    /usr/share/qemu/OVMF_CODE.fd \
    /run/current-system/sw/share/qemu/edk2-x86_64-code.fd \
    /usr/share/qemu/edk2-x86_64-code.fd \
    || find_glob_first \
      '/nix/store/*-OVMF-*/FV/OVMF_CODE.fd' \
      '/nix/store/*OVMF*/FV/OVMF_CODE.fd' \
      '/nix/store/*qemu*/share/qemu/edk2-x86_64-code.fd'
}

find_ovmf_vars() {
  local code_path="${1:-}"
  local code_dir=""
  local code_name=""
  if [ -n "$code_path" ]; then
    code_dir="$(dirname "$code_path")"
    code_name="$(basename "$code_path")"
  fi

  local derived1=""
  local derived2=""
  if [ "$code_name" = "OVMF_CODE.fd" ]; then
    derived1="$code_dir/OVMF_VARS.fd"
  elif [ "$code_name" = "edk2-x86_64-code.fd" ]; then
    derived1="$code_dir/edk2-i386-vars.fd"
    derived2="$code_dir/edk2-x86_64-vars.fd"
  fi

  find_first \
    "${FAUXNIX_OVMF_VARS:-}" \
    "$derived1" \
    "$derived2" \
    /run/current-system/sw/share/OVMF/OVMF_VARS.fd \
    /run/current-system/sw/FV/OVMF_VARS.fd \
    /usr/share/OVMF/OVMF_VARS.fd \
    /usr/share/qemu/OVMF_VARS.fd \
    /run/current-system/sw/share/qemu/edk2-i386-vars.fd \
    /usr/share/qemu/edk2-i386-vars.fd \
    || find_glob_first \
      '/nix/store/*-OVMF-*/FV/OVMF_VARS.fd' \
      '/nix/store/*OVMF*/FV/OVMF_VARS.fd' \
      '/nix/store/*qemu*/share/qemu/edk2-i386-vars.fd'
}

detect_vnc_listen() {
  if [ -n "${VNC_LISTEN:-}" ]; then
    printf '%s\n' "$VNC_LISTEN"
    return 0
  fi
  if command -v tailscale >/dev/null 2>&1; then
    local ip
    ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
    if [ -n "$ip" ]; then
      printf '%s\n' "$ip"
      return 0
    fi
  fi
  printf '%s\n' "$DEFAULT_TAILSCALE_IP"
}

echo -e "${GREEN}== macOS Sequoia VM Setup ==${NC}"
echo ""

MISSING=""
for cmd in qemu-system-x86_64 qemu-img curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    MISSING="$MISSING $cmd"
  fi
done

OVMF_CODE="$(find_ovmf_code || true)"
OVMF_VARS_TEMPLATE="$(find_ovmf_vars "$OVMF_CODE" || true)"
if [ -z "$OVMF_CODE" ] || [ -z "$OVMF_VARS_TEMPLATE" ]; then
  MISSING="$MISSING OVMF"
fi

if [ -n "$MISSING" ]; then
  echo -e "${YELLOW}Missing:$MISSING${NC}"
  if command -v nixos-rebuild >/dev/null 2>&1; then
    echo "NixOS packages: qemu_full OVMF.fd swtpm"
  elif command -v apt >/dev/null 2>&1; then
    echo "Install with: sudo apt install qemu-kvm qemu-utils ovmf"
  elif command -v dnf >/dev/null 2>&1; then
    echo "Install with: sudo dnf install @virtualization qemu-img edk2-ovmf"
  elif command -v pacman >/dev/null 2>&1; then
    echo "Install with: sudo pacman -S qemu-full edk2-ovmf"
  fi
  echo "Then re-run this script."
  exit 1
fi

OVMF_VARS="./OVMF_VARS.fd"
if [ ! -f "$OVMF_VARS" ]; then
  cp "$OVMF_VARS_TEMPLATE" "$OVMF_VARS"
  chmod u+w "$OVMF_VARS"
fi

echo -e "${GREEN}[ok]${NC} QEMU found"
echo -e "${GREEN}[ok]${NC} OVMF code: $OVMF_CODE"
echo -e "${GREEN}[ok]${NC} OVMF vars: $OVMF_VARS"

VNC_DISPLAY="${VNC_DISPLAY:-1}"
VNC_LISTEN="$(detect_vnc_listen)"
VNC_PORT="$((5900 + VNC_DISPLAY))"
VNC_TARGET="${VNC_LISTEN}:${VNC_DISPLAY}"

if [ ! -f "$OC_ISO" ]; then
  echo -e "${YELLOW}Downloading OpenCore ISO for QEMU...${NC}"
  curl -L -o "$OC_ISO" "$OC_ISO_URL"
  echo -e "${GREEN}[ok]${NC} Downloaded $OC_ISO"
else
  echo -e "${GREEN}[ok]${NC} $OC_ISO already present"
fi

MACOS_ISO="${MACOS_ISO:-}"
if [ -n "$MACOS_ISO" ] && [ -f "$MACOS_ISO" ]; then
  :
elif [ -f "macOS-Sequoia-15.7.7.iso" ]; then
  MACOS_ISO="macOS-Sequoia-15.7.7.iso"
elif [ -f "macOS-Sequoia.iso" ]; then
  MACOS_ISO="macOS-Sequoia.iso"
elif [ -f "$HOME/macOS-Sequoia-15.7.7.iso" ]; then
  MACOS_ISO="$HOME/macOS-Sequoia-15.7.7.iso"
elif [ -f "$HOME/macOS-Sequoia.iso" ]; then
  MACOS_ISO="$HOME/macOS-Sequoia.iso"
else
  echo -e "${YELLOW}macOS installer ISO not found in current directory.${NC}"
  read -r -p "Enter full path to macOS-Sequoia-15.7.7.iso: " MACOS_ISO
  if [ ! -f "$MACOS_ISO" ]; then
    echo "File not found. Copy the ISO from your Mac and re-run."
    exit 1
  fi
fi
echo -e "${GREEN}[ok]${NC} macOS installer: $MACOS_ISO"

if [ ! -f "$DISK" ]; then
  echo -e "${YELLOW}Creating $DISK_SIZE GB virtual disk...${NC}"
  qemu-img create -f qcow2 "$DISK" "${DISK_SIZE}G"
  echo -e "${GREEN}[ok]${NC} Created $DISK"
else
  echo -e "${GREEN}[ok]${NC} $DISK already exists"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} Starting macOS Sequoia VM ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "At the OpenCore picker, select 'macOS Installer'."
echo "Use Disk Utility to format the virtual disk as APFS,"
echo "then install macOS normally. It will reboot a few times."
echo ""
echo "TigerVNC: connect from Windows to ${VNC_LISTEN}:${VNC_PORT}"
echo ""

qemu-system-x86_64 \
  -machine q35,accel=kvm \
  -cpu host,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on \
  -smp 4 -m 8192 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$OVMF_VARS" \
  -drive file="$MACOS_ISO",format=raw,if=ide,index=0,media=cdrom \
  -drive file="$OC_ISO",format=raw,if=ide,index=1,media=cdrom \
  -drive file="$DISK",format=qcow2,if=ide,index=2,media=disk \
  -device e1000-82545em,netdev=net0 \
  -netdev user,id=net0 \
  -device usb-tablet \
  -usb \
  -vnc "$VNC_TARGET" 2>&1 || echo "If the VM exits, check the terminal output above for the QEMU error."
