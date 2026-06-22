# macOS Sequoia VM on Windows (VMware Workstation Pro)

VMware Workstation Pro is the easiest path on Windows — it has native GPU acceleration, solid performance, and the unlocker enables macOS guest support with a single patch.

---

## Files you need

Copy these from your Mac:

| File | Size | Where it goes |
|------|------|---------------|
| `macOS-Sequoia-15.7.7.iso` | 17 GB | Anywhere on Windows |
| `LongQT-OpenCore-v0.7.iso` | 16 MB | Anywhere on Windows |

Download the OpenCore ISO from:
```
https://github.com/LongQT-sea/OpenCore-ISO/releases/download/v0.7/LongQT-OpenCore-v0.7.iso
```

---

## Step 1: Install VMware Workstation Pro

1. Go to https://support.broadcom.com/ (free for personal use, registration required)
2. Search for "VMware Workstation Pro"
3. Download the latest Windows version and install it
4. Restart your computer

---

## Step 2: Install macOS Unlocker

VMware blocks macOS as a guest OS by default. The unlocker patches this.

1. Download from https://github.com/DrDonk/unlocker/releases
2. Extract the ZIP
3. **Right-click `win-install.cmd` → Run as Administrator**
4. Wait for the script to finish (a console window opens and closes)
5. This enables "Apple Mac OS X" as an option in VMware

---

## Step 3: Create the VM

1. Open **VMware Workstation Pro**
2. Click **Create a New Virtual Machine**
3. Select **Custom (advanced)** → Next
4. **Workstation 17.x** → Next
5. **I will install the operating system later** → Next
6. Guest operating system: **Apple Mac OS X**
   - Version: **macOS 14** (Sequoia isn't in the list but 14 or later works)
7. Name: `macOS Sequoia`
8. CPUs: **2** (or more)
   - Check **Virtualize Intel VT-x/EPT or AMD-V/RVI**
9. Memory: **8192 MB**
10. Network: **NAT** (default)
11. I/O Controller: **LSI Logic SAS**
12. Disk type: **SATA**
13. Disk size: **80 GB**
    - **Store virtual disk as a single file**
14. Click **Finish**

---

## Step 4: Configure the VM

1. Select your VM and click **Edit virtual machine settings**
2. **Memory**: 8192 MB
3. **Processors**: 2+, check "Virtualize Intel VT-x/EPT"
4. **CD/DVD (SATA)**: Browse → select `macOS-Sequoia-15.7.7.iso`
   - Check **Connect at power on**
5. Click **Add** → **CD/DVD Drive** → **SATA**
   - Browse → select `LongQT-OpenCore-v0.7.iso`
   - Check **Connect at power on**
6. **Display**: Check **Accelerate 3D graphics** (optional but helps)
7. Click **OK**

---

## Step 5: Boot and Install

1. Click **Power on this VM**
2. The OpenCore boot picker appears — select **macOS Installer**
3. When macOS recovery loads, open **Disk Utility**
4. Select the VMware virtual disk → **Erase**
   - Name: `Macintosh HD`
   - Format: APFS
   - Scheme: GUID Partition Map
5. Close Disk Utility → select **Reinstall macOS Sequoia**
6. Follow the on-screen installer. The VM will reboot several times — OpenCore picks the right boot option automatically.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Apple Mac OS X" not in the OS list | Re-run `win-install.cmd` as Administrator |
| VM hangs at "UEFI Interactive Shell" | OpenCore ISO isn't set as the first boot CD |
| Black screen after OpenCore | Remove `-v` debugging from OpenCore config, or wait longer |
| Slow performance | Increase CPU cores, enable 3D acceleration |
