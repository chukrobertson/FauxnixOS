# macOS Sequoia VM on Linux (QEMU/KVM)

Requires a Linux machine with a CPU that supports hardware virtualization (Intel VT-x or AMD-V). The script handles everything — just run it.

---

## Quick Start

```
# 1. Copy files to your Linux machine
scp macos-vm.sh macOS-Sequoia-15.7.7.iso user@linux-host:~/

# 2. SSH into it
ssh user@linux-host

# 3. Run the script
./macos-vm.sh
```

The script will:
- Check for QEMU/KVM and OVMF (and tell you how to install if missing)
- Download `LongQT-OpenCore-v0.7.iso` automatically
- Prompt for the macOS ISO path (or find it in the current dir)
- Create an 80 GB virtual disk (`macos-disk.qcow2`)
- Boot the VM and expose it over VNC for TigerVNC
- Mount the macOS installer ISO as DVD slot 1 and the OpenCore helper ISO as
  DVD slot 2; this keeps the OpenCore picker from showing only utility entries.

By default on the Fauxnix ThinkPad, TigerVNC should connect to:

```text
100.97.123.113:5901
```

Override with `VNC_LISTEN=<ip>` and `VNC_DISPLAY=<n>` if needed.
Set `MACOS_ISO=<path>` to force a specific installer ISO; on Fauxnix the script
also checks `/home/chvk/macOS-Sequoia-15.7.7.iso`.

---

## Manual Steps (if the script doesn't work)

### Prerequisites

NixOS:
```nix
environment.systemPackages = with pkgs; [
  qemu_full
  OVMF.fd
  swtpm
];
```

The script auto-detects OVMF from the Nix store and copies the firmware vars
file to a local writable `OVMF_VARS.fd`.

Debian/Ubuntu:
```bash
sudo apt install qemu-kvm libvirt-daemon qemu-system qemu-utils ovmf
```

Fedora:
```bash
sudo dnf install @virtualization qemu-img edk2-ovmf
```

Arch:
```bash
sudo pacman -S qemu-full edk2-ovmf
```

### Download OpenCore ISO

```bash
curl -LO https://github.com/LongQT-sea/OpenCore-ISO/releases/download/v0.7/LongQT-OpenCore-v0.7.iso
```

### Create virtual disk

```bash
qemu-img create -f qcow2 macos-disk.qcow2 80G
```

### Boot the VM

If you skip `macos-vm.sh`, set `OVMF_CODE` to your platform's OVMF code file
and copy the matching vars file to a writable path:

```bash
OVMF_CODE=/path/to/OVMF_CODE.fd
cp /path/to/OVMF_VARS.fd ./OVMF_VARS.fd
OVMF_VARS=$PWD/OVMF_VARS.fd
```

```bash
qemu-system-x86_64 \
  -machine q35,accel=kvm \
  -cpu host,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on \
  -smp 4 -m 8192 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$OVMF_VARS" \
  -drive file=macOS-Sequoia-15.7.7.iso,format=raw,if=ide,index=0,media=cdrom \
  -drive file=LongQT-OpenCore-v0.7.iso,format=raw,if=ide,index=1,media=cdrom \
  -drive file=macos-disk.qcow2,format=qcow2,if=ide,index=2,media=disk \
  -device e1000-82545em,netdev=net0 \
  -netdev user,id=net0 \
  -vnc 100.97.123.113:1
```

### Headless server (SSH-only, no monitor)

Use VNC instead:

```bash
qemu-system-x86_64 \
  -machine q35,accel=kvm \
  -cpu host,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on \
  -smp 4 -m 8192 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$OVMF_VARS" \
  -drive file=macOS-Sequoia-15.7.7.iso,format=raw,if=ide,index=0,media=cdrom \
  -drive file=LongQT-OpenCore-v0.7.iso,format=raw,if=ide,index=1,media=cdrom \
  -drive file=macos-disk.qcow2,format=qcow2,if=ide,index=2,media=disk \
  -device e1000-82545em,netdev=net0 \
  -netdev user,id=net0 \
  -vnc 100.97.123.113:1
```

Then connect with any VNC client to `<linux-ip>:5901`.

---

## Installation Steps (inside the VM)

1. At the OpenCore boot picker, select **macOS Installer**
2. When the macOS recovery screen appears, open **Disk Utility**
3. Select the QEMU hard disk, click **Erase**
   - Name: `Macintosh HD`
   - Format: APFS
   - Scheme: GUID Partition Map
4. Close Disk Utility, select **Reinstall macOS Sequoia**
5. Follow the prompts. The VM will reboot several times — OpenCore handles it.
