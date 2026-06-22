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
- Attach the macOS installer image as snapshot-backed SATA block media on slot
  1 and the OpenCore helper ISO as SATA DVD media on slot 2, then boot OpenCore
  from that second slot. The Sequoia image is Apple-partitioned 512-byte media,
  not a normal ISO9660 optical disc.

By default on the Fauxnix ThinkPad, TigerVNC should connect to:

```text
100.97.123.113:5901
```

Override with `VNC_LISTEN=<ip>` and `VNC_DISPLAY=<n>` if needed.
Set `MACOS_ISO=<path>` to force a specific installer ISO; on Fauxnix the script
prefers `/home/chvk/BaseSystem-Sequoia.raw` when present, then falls back to
`/home/chvk/macOS-Sequoia-15.7.7.iso`.
The VM defaults to 8192 MB RAM, 4 cores, and a `vmxnet3` NIC. Override with
`MEMORY_MB=<mb>`, `SMP_CORES=<n>`, or `NET_DEVICE=<qemu-device>` if needed.
The backing disk file defaults to `macos-disk.qcow2`; the macOS volume inside
that disk can be named `MacOSVM` in Disk Utility. Override the file path with
`DISK=<path>` only if you intentionally want a different qcow2.

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
  -device ich9-ahci,id=sata \
  -drive id=MacInstaller,if=none,format=raw,snapshot=on,file=BaseSystem-Sequoia.raw \
  -device ide-hd,bus=sata.0,drive=MacInstaller \
  -drive id=OpenCore,if=none,format=raw,file=LongQT-OpenCore-v0.7.iso,media=cdrom \
  -device ide-cd,bus=sata.1,drive=OpenCore,bootindex=1 \
  -drive id=MacDisk,if=none,format=qcow2,file=macos-disk.qcow2 \
  -device ide-hd,bus=sata.2,drive=MacDisk \
  -device vmxnet3,netdev=net0 \
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
  -device ich9-ahci,id=sata \
  -drive id=MacInstaller,if=none,format=raw,snapshot=on,file=BaseSystem-Sequoia.raw \
  -device ide-hd,bus=sata.0,drive=MacInstaller \
  -drive id=OpenCore,if=none,format=raw,file=LongQT-OpenCore-v0.7.iso,media=cdrom \
  -device ide-cd,bus=sata.1,drive=OpenCore,bootindex=1 \
  -drive id=MacDisk,if=none,format=qcow2,file=macos-disk.qcow2 \
  -device ide-hd,bus=sata.2,drive=MacDisk \
  -device vmxnet3,netdev=net0 \
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
