# macOS Sequoia VM on Windows (QEMU)

If you prefer QEMU over VMware, this works but performance is lower since Windows doesn't have native KVM. Use the VMware guide instead if you want smoother graphics.

---

## Files you need

| File | Notes |
|------|-------|
| `macOS-Sequoia-15.7.7.iso` | macOS installer (17 GB) |
| `LongQT-OpenCore-v0.7.iso` | Download from: https://github.com/LongQT-sea/OpenCore-ISO/releases/download/v0.7/LongQT-OpenCore-v0.7.iso |

Place both in the same folder (e.g. `C:\macos-vm`).

---

## Step 1: Install QEMU

1. Download the Windows installer from:
   https://qemu.weilnetz.de/w64/
2. Choose the latest `qemu-w64-setup-*.exe`
3. Install to the default location (`C:\Program Files\qemu`)
4. Note the OVMF (UEFI) files are at:
   ```
   C:\Program Files\qemu\share\edk2-x86_64-code.fd
   ```

---

## Step 2: Create the virtual disk

Open **Command Prompt as Administrator** and run:

```bat
cd C:\macos-vm
qemu-img create -f qcow2 macos-disk.qcow2 80G
```

---

## Step 3: Boot the VM

```bat
qemu-system-x86_64 ^
  -machine q35 ^
  -cpu host,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on ^
  -smp 4 -m 8192 ^
  -drive if=pflash,format=raw,readonly=on,file="C:\Program Files\qemu\share\edk2-x86_64-code.fd" ^
  -drive file=LongQT-OpenCore-v0.7.iso,format=raw,if=ide,index=0,media=cdrom ^
  -drive file=macOS-Sequoia-15.7.7.iso,format=raw,if=ide,index=1,media=cdrom ^
  -drive file=macos-disk.qcow2,format=qcow2,if=virtio ^
  -device virtio-net-pci,netdev=net0 ^
  -netdev user,id=net0 ^
  -display gtk
```

Save this as `run.bat` in `C:\macos-vm` so you don't have to retype it.

---

## Installation Steps (inside the VM)

1. At the OpenCore boot picker, select **macOS Installer**
2. Open **Disk Utility**
3. Select the QEMU VIRTIO disk → **Erase**
   - Name: `Macintosh HD`
   - Format: APFS
   - Scheme: GUID Partition Map
4. Close Disk Utility → **Reinstall macOS Sequoia**
5. Follow the installer. It reboots several times — OpenCore handles it.

---

## Notes

- QEMU on Windows lacks hardware acceleration, so the VM will feel sluggish compared to VMware or Linux/KVM
- The VM is NAT'd by default — macOS gets IP `10.0.2.15`, host is `10.0.2.2`
- For better performance, consider enabling WHPX acceleration:
  ```bat
  -accel whpx
  ```
  Add this flag if your CPU supports Windows Hypervisor Platform
