"""QEMU command-line builder for macOS and Windows VMs.

Produces a qemu_argv list compatible with QemuVMProvider.
The provider appends -qmp, -vnc, and -display flags automatically,
so those are intentionally omitted here.
"""

from __future__ import annotations

import json
import os
import platform
import glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class VMSpec:
    """Describes a VM configuration for qemu_argv generation."""

    # VM identity
    kind: Literal["macos", "windows"] = "macos"
    name: str = "VM"

    # Hardware
    memory_mb: int = 8192
    smp_cores: int = 4
    arch: Literal["x86_64", "aarch64"] = "x86_64"

    # Firmware
    ovmf_code: str = "/usr/share/OVMF/OVMF_CODE.fd"
    ovmf_vars: str | None = None  # auto-derived if None

    # Disk
    disk_path: str = "macos-disk.qcow2"
    disk_format: str = "qcow2"
    disk_if: str = "virtio"

    # macOS specific
    opencore_iso: str | None = None
    installer_iso: str | None = None

    # Windows specific
    virtio_iso: str | None = None
    tpm: bool = False        # swtpm for Windows 11
    tpm_socket: str = "/var/run/swtpm.sock"

    # Network
    netdev_id: str = "net0"
    mac_address: str | None = None
    hostfwd: list[str] | None = None  # e.g. ["tcp::2222-:22"]

    # Extra flags appended verbatim
    extra_args: list[str] = field(default_factory=list)

    # Path to qemu binary
    qemu_bin: str = ""

    def __post_init__(self):
        if not self.qemu_bin:
            if self.arch == "aarch64":
                self.qemu_bin = "qemu-system-aarch64"
            else:
                self.qemu_bin = "qemu-system-x86_64"
        self.ovmf_code = _resolve_ovmf_code(self.ovmf_code) or self.ovmf_code
        if self.ovmf_vars is None:
            self.ovmf_vars = (
                _resolve_ovmf_vars(self.ovmf_code, None)
                or _derived_ovmf_vars_path(self.ovmf_code)
            )
        else:
            self.ovmf_vars = _resolve_ovmf_vars(self.ovmf_code, self.ovmf_vars) or self.ovmf_vars
        if self.hostfwd is None:
            self.hostfwd = []
        if self.tpm and self.tpm_socket == "/var/run/swtpm.sock":
            safe = self.name.lower().replace(" ", "-").replace("/", "_")
            self.tpm_socket = f"/tmp/fauxnix-tpm-{safe}.sock"


def build_qemu_argv(spec: VMSpec) -> list[str]:
    """Build a QEMU command-line list from a VMSpec.

    The result does NOT include -qmp, -vnc, or -display flags —
    QemuVMProvider._build_qemu_cmd adds those automatically.
    """
    argv = [spec.qemu_bin]

    # Machine
    _add(argv, "-machine", _machine(spec))

    # CPU
    _add(argv, "-cpu", _cpu(spec))

    # SMP / memory
    _add(argv, "-smp", str(spec.smp_cores))
    _add(argv, "-m", str(spec.memory_mb))

    # OVMF firmware
    _add(argv, "-drive", f"if=pflash,format=raw,readonly=on,file={spec.ovmf_code}")
    _add(argv, "-drive", f"if=pflash,format=raw,file={spec.ovmf_vars}")

    # Drives
    for d in _drives(spec):
        _add(argv, "-drive", d)

    # Network. macOS has native Intel e1000 support; VirtIO depends on
    # additional guest drivers and is a worse default for first boot.
    net_device = "e1000-82545em" if spec.kind == "macos" else "virtio-net-pci"
    net_device = f"{net_device},netdev={spec.netdev_id}"
    if spec.mac_address:
        net_device = f"{net_device},mac={spec.mac_address}"
    _add(argv, "-device", net_device)
    netdev_opts = f"user,id={spec.netdev_id}"
    for fwd in spec.hostfwd:
        netdev_opts += f",hostfwd={fwd}"
    _add(argv, "-netdev", netdev_opts)

    # USB tablet for cursor sync
    _add(argv, "-device", "usb-tablet")

    # TPM 2.0 (required for Windows 11)
    if spec.tpm:
        _add(argv, "-chardev", f"socket,id=chrtpm,path={spec.tpm_socket}")
        _add(argv, "-tpmdev", f"emulator,id=tpm0,chardev=chrtpm")
        _add(argv, "-device", "tpm-tis,tpmdev=tpm0")
        _add(argv, "-global", "ICH9-LPC.disable_s3=1")

    # Extra args
    argv.extend(spec.extra_args)

    return argv


def build_macos_spec(
    disk_path: str,
    opencore_iso: str,
    installer_iso: str,
    *,
    name: str = "macOS Sequoia",
    memory_mb: int = 8192,
    smp_cores: int = 4,
    ovmf_code: str = "/usr/share/OVMF/OVMF_CODE.fd",
    ovmf_vars: str | None = None,
    hostfwd: list[str] | None = None,
) -> VMSpec:
    """Convenience: build a VMSpec for macOS Sequoia."""
    return VMSpec(
        kind="macos",
        name=name,
        memory_mb=memory_mb,
        smp_cores=smp_cores,
        ovmf_code=ovmf_code,
        ovmf_vars=ovmf_vars,
        disk_path=disk_path,
        disk_format="qcow2",
        disk_if="ide",
        opencore_iso=opencore_iso,
        installer_iso=installer_iso,
        hostfwd=hostfwd or ["tcp::2222-:22"],
        extra_args=["-usb"],
    )


def build_windows_spec(
    disk_path: str,
    *,
    name: str = "Windows 11",
    install_iso: str | None = None,
    virtio_iso: str | None = None,
    memory_mb: int = 8192,
    smp_cores: int = 4,
    tpm: bool = True,
    tpm_socket: str | None = None,
    ovmf_code: str = "/usr/share/OVMF/OVMF_CODE.fd",
    ovmf_vars: str | None = None,
    hostfwd: list[str] | None = None,
) -> VMSpec:
    """Convenience: build a VMSpec for Windows 10/11."""
    extra: list[str] = []
    if install_iso:
        extra.extend(["-cdrom", install_iso])
    return VMSpec(
        kind="windows",
        name=name,
        memory_mb=memory_mb,
        smp_cores=smp_cores,
        ovmf_code=ovmf_code,
        ovmf_vars=ovmf_vars,
        disk_path=disk_path,
        disk_format="qcow2",
        disk_if="virtio",
        virtio_iso=virtio_iso,
        tpm=tpm,
        tpm_socket=tpm_socket or f"/tmp/fauxnix-tpm-{name.lower().replace(' ', '-')}.sock",
        hostfwd=hostfwd or ["tcp::3389-:3389"],
        extra_args=extra,
    )


def load_env_config(path: str) -> dict:
    """Load environments.json and return parsed config."""
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    return json.loads(p.read_text("utf-8"))


def build_env_qemu_argv(config: dict) -> list[str] | None:
    """Build qemu_argv from an environment config entry that has 'builder'.

    Returns None if the entry has no 'builder' field or the builder is unknown.
    """
    builder = config.get("builder")
    if builder is None or builder == "none":
        return None

    if builder == "macos":
        spec = build_macos_spec(
            disk_path=config.get("disk_path", "macos-disk.qcow2"),
            opencore_iso=config.get("opencore_iso", ""),
            installer_iso=config.get("installer_iso", ""),
            name=config.get("name", "macOS VM"),
            memory_mb=config.get("memory_mb", 8192),
            smp_cores=config.get("smp_cores", config.get("smp", 4)),
            ovmf_code=config.get("ovmf_code", "/usr/share/OVMF/OVMF_CODE.fd"),
            ovmf_vars=config.get("ovmf_vars"),
            hostfwd=config.get("hostfwd"),
        )
        return build_qemu_argv(spec)

    if builder == "windows":
        spec = build_windows_spec(
            disk_path=config.get("disk_path", "win11.qcow2"),
            name=config.get("name", "Windows VM"),
            install_iso=config.get("install_iso"),
            virtio_iso=config.get("virtio_iso"),
            memory_mb=config.get("memory_mb", 8192),
            smp_cores=config.get("smp_cores", config.get("smp", 4)),
            tpm=config.get("tpm", True),
            tpm_socket=config.get("tpm_socket"),
            ovmf_code=config.get("ovmf_code", "/usr/share/OVMF/OVMF_CODE.fd"),
            ovmf_vars=config.get("ovmf_vars"),
            hostfwd=config.get("hostfwd"),
        )
        return build_qemu_argv(spec)

    return None


# ── Internal helpers ──────────────────────────────────────────────


def _add(argv: list[str], flag: str, value: str) -> None:
    argv.append(flag)
    argv.append(value)


def _first_existing(paths: list[str | None]) -> str:
    for raw in paths:
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.exists():
            return str(path)
    return ""


def _first_glob(patterns: list[str]) -> str:
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return ""


def _resolve_ovmf_code(requested: str | None) -> str:
    explicit = _first_existing([
        os.environ.get("FAUXNIX_OVMF_CODE"),
        requested,
    ])
    if explicit:
        return explicit

    common = _first_existing([
        "/run/current-system/sw/share/OVMF/OVMF_CODE.fd",
        "/run/current-system/sw/FV/OVMF_CODE.fd",
        "/usr/share/OVMF/OVMF_CODE.fd",
        "/usr/share/qemu/OVMF_CODE.fd",
        "/run/current-system/sw/share/qemu/edk2-x86_64-code.fd",
        "/usr/share/qemu/edk2-x86_64-code.fd",
    ])
    if common:
        return common

    return _first_glob([
        "/nix/store/*-OVMF-*/FV/OVMF_CODE.fd",
        "/nix/store/*OVMF*/FV/OVMF_CODE.fd",
        "/nix/store/*qemu*/share/qemu/edk2-x86_64-code.fd",
    ])


def _resolve_ovmf_vars(code_path: str | None, requested: str | None) -> str:
    explicit = _first_existing([
        os.environ.get("FAUXNIX_OVMF_VARS"),
        requested,
    ])
    if explicit:
        return explicit

    derived: list[str | None] = []
    if code_path:
        code = Path(str(code_path)).expanduser()
        name = code.name
        if name == "OVMF_CODE.fd":
            derived.append(str(code.with_name("OVMF_VARS.fd")))
        if name == "edk2-x86_64-code.fd":
            derived.append(str(code.with_name("edk2-i386-vars.fd")))
            derived.append(str(code.with_name("edk2-x86_64-vars.fd")))

    common = _first_existing(derived + [
        "/run/current-system/sw/share/OVMF/OVMF_VARS.fd",
        "/run/current-system/sw/FV/OVMF_VARS.fd",
        "/usr/share/OVMF/OVMF_VARS.fd",
        "/usr/share/qemu/OVMF_VARS.fd",
        "/run/current-system/sw/share/qemu/edk2-i386-vars.fd",
        "/usr/share/qemu/edk2-i386-vars.fd",
    ])
    if common:
        return common

    return _first_glob([
        "/nix/store/*-OVMF-*/FV/OVMF_VARS.fd",
        "/nix/store/*OVMF*/FV/OVMF_VARS.fd",
        "/nix/store/*qemu*/share/qemu/edk2-i386-vars.fd",
    ])


def _derived_ovmf_vars_path(code_path: str | None) -> str:
    if not code_path:
        return "/usr/share/OVMF/OVMF_VARS.fd"
    code = Path(str(code_path)).expanduser()
    if code.name == "OVMF_CODE.fd":
        return str(code.with_name("OVMF_VARS.fd"))
    if code.name == "edk2-x86_64-code.fd":
        return str(code.with_name("edk2-i386-vars.fd"))
    return "/usr/share/OVMF/OVMF_VARS.fd"


def _machine(spec: VMSpec) -> str:
    base = "q35"
    if spec.arch == "aarch64":
        base = "virt"
    return f"{base},accel=kvm"


def _cpu(spec: VMSpec) -> str:
    if spec.kind == "macos":
        # macOS needs invariant TSC, VMware cpuid freq, and GenuineIntel vendor
        return "host,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on"
    return "host"


def _drives(spec: VMSpec) -> list[str]:
    drives: list[str] = []

    if spec.kind == "macos":
        # Mirror the working VMware layout: macOS installer in DVD slot 1,
        # OpenCore/helper ISO in DVD slot 2.
        if spec.installer_iso:
            drives.append(
                f"file={spec.installer_iso},format=raw,if=ide,index=0,media=cdrom"
            )
        if spec.opencore_iso:
            opencore_index = 1 if spec.installer_iso else 0
            drives.append(
                f"file={spec.opencore_iso},format=raw,if=ide,index={opencore_index},media=cdrom"
            )
    else:
        if spec.opencore_iso:
            drives.append(
                f"file={spec.opencore_iso},format=raw,if=ide,index=0,media=cdrom"
            )
        if spec.installer_iso:
            drives.append(
                f"file={spec.installer_iso},format=raw,if=ide,index=1,media=cdrom"
            )

    # Windows: virtio drivers ISO
    if spec.virtio_iso:
        drives.append(
            f"file={spec.virtio_iso},format=raw,if=ide,index=2,media=cdrom"
        )

    # Main disk. Use IDE for the default macOS installer path because stock
    # macOS does not reliably see VirtIO block devices.
    disk = f"file={spec.disk_path},format={spec.disk_format},if={spec.disk_if}"
    if spec.kind == "macos" and spec.disk_if == "ide":
        disk += ",index=2,media=disk"
    drives.append(disk)

    return drives
