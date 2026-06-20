"""QEMU-based VM display source with QMP control.

Launches a QEMU VM in headless mode, captures frames via screendump over QMP,
and forwards input via QMP input-send-event.

The contract with DisplayCardNode is the same SurfaceProvider interface used by
local-app, fauxpass-app, etc. This makes VM cards first-class citizens on the
canvas.

Future: replace screendump capture with IVSHMEM + Looking Glass for
GPU-accelerated frame transfer and lower-latency input.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Thread, Event

from .base import SurfaceProvider, InputEvent


# Maps a printable character to a QMP QKeyCode string.
_CHAR_TO_QCODE: dict[str, str] = {
    # lowercase
    'a': 'key_a', 'b': 'key_b', 'c': 'key_c', 'd': 'key_d', 'e': 'key_e',
    'f': 'key_f', 'g': 'key_g', 'h': 'key_h', 'i': 'key_i', 'j': 'key_j',
    'k': 'key_k', 'l': 'key_l', 'm': 'key_m', 'n': 'key_n', 'o': 'key_o',
    'p': 'key_p', 'q': 'key_q', 'r': 'key_r', 's': 'key_s', 't': 'key_t',
    'u': 'key_u', 'v': 'key_v', 'w': 'key_w', 'x': 'key_x', 'y': 'key_y',
    'z': 'key_z',
    # uppercase
    'A': ('key_shift', 'key_a'), 'B': ('key_shift', 'key_b'),
    'C': ('key_shift', 'key_c'), 'D': ('key_shift', 'key_d'),
    'E': ('key_shift', 'key_e'), 'F': ('key_shift', 'key_f'),
    'G': ('key_shift', 'key_g'), 'H': ('key_shift', 'key_h'),
    'I': ('key_shift', 'key_i'), 'J': ('key_shift', 'key_j'),
    'K': ('key_shift', 'key_k'), 'L': ('key_shift', 'key_l'),
    'M': ('key_shift', 'key_m'), 'N': ('key_shift', 'key_n'),
    'O': ('key_shift', 'key_o'), 'P': ('key_shift', 'key_p'),
    'Q': ('key_shift', 'key_q'), 'R': ('key_shift', 'key_r'),
    'S': ('key_shift', 'key_s'), 'T': ('key_shift', 'key_t'),
    'U': ('key_shift', 'key_u'), 'V': ('key_shift', 'key_v'),
    'W': ('key_shift', 'key_w'), 'X': ('key_shift', 'key_x'),
    'Y': ('key_shift', 'key_y'), 'Z': ('key_shift', 'key_z'),
    # digits
    '0': 'key_0', '1': 'key_1', '2': 'key_2', '3': 'key_3', '4': 'key_4',
    '5': 'key_5', '6': 'key_6', '7': 'key_7', '8': 'key_8', '9': 'key_9',
    # symbols
    ' ': 'key_space', '\n': 'key_ret', '\t': 'key_tab',
    '-': 'key_minus', '=': 'key_equal', '[': 'key_bracket_left',
    ']': 'key_bracket_right', '\\': 'key_backslash', ';': 'key_semicolon',
    "'": 'key_apostrophe', '`': 'key_grave_accent', ',': 'key_comma',
    '.': 'key_dot', '/': 'key_slash',
    # shifted symbols
    '~': ('key_shift', 'key_grave_accent'),
    '!': ('key_shift', 'key_1'), '@': ('key_shift', 'key_2'),
    '#': ('key_shift', 'key_3'), '$': ('key_shift', 'key_4'),
    '%': ('key_shift', 'key_5'), '^': ('key_shift', 'key_6'),
    '&': ('key_shift', 'key_7'), '*': ('key_shift', 'key_8'),
    '(': ('key_shift', 'key_9'), ')': ('key_shift', 'key_0'),
    '_': ('key_shift', 'key_minus'), '+': ('key_shift', 'key_equal'),
    '{': ('key_shift', 'key_bracket_left'),
    '}': ('key_shift', 'key_bracket_right'),
    '|': ('key_shift', 'key_backslash'),
    ':': ('key_shift', 'key_semicolon'),
    '"': ('key_shift', 'key_apostrophe'),
    '<': ('key_shift', 'key_comma'),
    '>': ('key_shift', 'key_dot'),
    '?': ('key_shift', 'key_slash'),
}

# Maps QEMU QKeyCode strings to QMP key names (without the 'key_' prefix).
_QCODE_TO_NAME: dict[str, str] = {}
# Will be populated below module init trick or lazily.

# Buttons: InputEvent.button (1=left, 2=middle, 3=right) → QMP button name
_BUTTON_MAP = {1: 'left', 2: 'middle', 3: 'right'}


def _qcode_name(qcode: str) -> str:
    """Strip 'key_' prefix from a QKeyCode string."""
    return qcode[4:] if qcode.startswith('key_') else qcode


class QemuVMProvider(SurfaceProvider):
    """VM display source backed by QEMU with QMP control.

    The provider manages a single QEMU process. Frames are captured via
    screendump over the QMP socket. Input is forwarded via QMP
    input-send-event.

    Source spec fields used:
        kind: 'looking-glass-vm' (or 'qemu-vm' alias)
        qemu_argv: list[str] — QEMU command-line arguments
        qmp_path: str — path for the QMP Unix socket (default:
            /tmp/fauxnix-qemu-{id}.sock)
        vnc_display: int — VNC display number (default: 1 + hash(id))
        width, height: int — framebuffer dimensions
        memory_mb: int — RAM in MB
        smp: int — CPU cores
        disk: str — path to disk image
        boot_iso: str — path to boot/installer ISO
        opencore_iso: str — path to OpenCore ISO
        name: str — display name
    """

    def __init__(
        self,
        *,
        qemu_argv: list[str] | None = None,
        qmp_path: str = "",
        vnc_display: int = 1,
        width: int = 1280,
        height: int = 720,
        instance_id: str = "",
        name: str = "VM",
    ):
        self._qemu_argv = qemu_argv or []
        self._qmp_path = qmp_path or f"/tmp/fauxnix-qemu-{instance_id or id(self)}.sock"
        self._vnc_display = vnc_display
        self._width = max(320, width)
        self._height = max(240, height)
        self._name = name
        self._instance_id = instance_id or str(id(self))

        self._process: subprocess.Popen | None = None
        self._qmp_sock: socket.socket | None = None
        self._running = False
        self._last_frame: tuple[bytes, int, int] | None = None
        self._frame_lock = Thread._lock if hasattr(Thread, '_lock') else None

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._ensure_qmp_socket_removed()
        cmd = self._build_qemu_cmd()
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError("qemu-system-x86_64 not found — is QEMU installed?")
        # Wait briefly for QMP socket to appear
        for _ in range(20):
            if Path(self._qmp_path).exists():
                break
            time.sleep(0.2)
        if not Path(self._qmp_path).exists():
            self._running = False
            raise RuntimeError(f"QEMU QMP socket not found at {self._qmp_path}")
        self._connect_qmp()
        self._running = True

    def stop(self) -> None:
        if not self._running and self._process is None:
            return
        try:
            self._qmp_cmd("quit")
        except Exception:
            pass
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
                self._process.wait(timeout=3)
        self._process = None
        self._running = False
        self._last_frame = None
        self._disconnect_qmp()
        self._ensure_qmp_socket_removed()

    def is_running(self) -> bool:
        if self._process is None:
            return False
        if self._process.poll() is not None:
            self._running = False
            return False
        return self._running

    # ── Frame capture ──────────────────────────────────────────────────

    def get_frame(self) -> tuple[bytes, int, int] | None:
        return self._last_frame

    def poll(self) -> None:
        """Capture a frame via QMP screendump."""
        if not self.is_running():
            return
        try:
            data = self._screendump()
            if data is not None:
                self._last_frame = data
        except Exception:
            pass

    def _screendump(self) -> tuple[bytes, int, int] | None:
        """Capture a PPM screendump and return RGBA bytes.

        Uses a temp file to avoid buffering issues with QEMU's screendump
        command. Parses PPM P6 format and converts to RGBA8888.
        """
        fd, path = tempfile.mkstemp(suffix=".ppm", prefix="fauxnix-")
        os.close(fd)
        try:
            self._qmp_cmd("screendump", {"filename": path})
            if not Path(path).exists():
                return None
            raw = Path(path).read_bytes()
            if len(raw) < 32:
                return None

            # Parse PPM P6: "P6\n<w> <h>\n255\n" then RGB data
            if raw[0:2] != b"P6":
                return None
            header_end = raw.index(b"\x00") if b"\x00" in raw[:64] else raw.index(b"\n", 3)
            header = raw[2:header_end].decode("ascii", errors="replace").strip()
            parts = header.split()
            if len(parts) < 2:
                return None
            w, h = int(parts[0]), int(parts[1])
            # Data starts after header + newline
            data_start = header_end + 1
            # Skip maxval line if present
            while data_start < len(raw) and raw[data_start:data_start+1] not in (b'\n',):
                data_start += 1
            data_start += 1
            rgb = raw[data_start:data_start + w * h * 3]

            # Convert RGB → RGBA
            rgba = bytearray(len(rgb) // 3 * 4)
            for i in range(0, len(rgb), 3):
                dst = i // 3 * 4
                rgba[dst] = rgb[i]
                rgba[dst + 1] = rgb[i + 1]
                rgba[dst + 2] = rgb[i + 2]
                rgba[dst + 3] = 255

            return (bytes(rgba), w, h)
        except Exception:
            return None
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    # ── Input forwarding ────────────────────────────────────────────────

    def send_input(self, event: InputEvent) -> None:
        if not self.is_running():
            return
        try:
            if event.type in ("pointer_move", "button_press", "button_release"):
                self._send_pointer(event)
            elif event.type in ("key_press", "key_release"):
                self._send_key(event)
            elif event.type == "axis":
                self._send_axis(event)
            elif event.type == "text":
                self._send_text(event)
        except Exception:
            pass

    def _send_pointer(self, event: InputEvent) -> None:
        events = []
        # Absolute coordinates (normalized to QEMU 0xFFFF range)
        abs_x = int(max(0, event.x) / max(1, self._width) * 0xFFFF)
        abs_y = int(max(0, event.y) / max(1, self._height) * 0xFFFF)
        events.append({"type": "abs", "data": {"axis": "x", "value": abs_x}})
        events.append({"type": "abs", "data": {"axis": "y", "value": abs_y}})
        if event.type in ("button_press", "button_release"):
            btn = _BUTTON_MAP.get(event.button or 1, "left")
            action = "press" if event.type == "button_press" else "release"
            events.append({"type": "btn", "data": {"action": action, "button": btn}})
        self._qmp_cmd("input-send-event", {"events": events})

    def _send_key(self, event: InputEvent) -> None:
        if event.key is None:
            return
        # Try to look up the key as a QKeyCode by character
        char = chr(event.key) if 32 <= event.key <= 126 else ""
        if char and char in _CHAR_TO_QCODE:
            mapping = _CHAR_TO_QCODE[char]
            if isinstance(mapping, tuple):
                shift_qcode, qcode = mapping
                action = "press" if event.type == "key_press" else "release"
                self._qmp_cmd("input-send-event", {
                    "events": [
                        {"type": "key", "data": {"action": action, "key": {"type": "qcode", "data": _qcode_name(shift_qcode)}}},
                        {"type": "key", "data": {"action": action, "key": {"type": "qcode", "data": _qcode_name(qcode)}}},
                    ]
                })
            else:
                action = "press" if event.type == "key_press" else "release"
                self._qmp_cmd("input-send-event", {
                    "events": [
                        {"type": "key", "data": {"action": action, "key": {"type": "qcode", "data": _qcode_name(mapping)}}},
                    ]
                })

    def _send_axis(self, event: InputEvent) -> None:
        direction = "down" if (event.delta_y or 0) > 0 else "up"
        self._qmp_cmd("input-send-event", {
            "events": [
                {"type": "abs", "data": {"axis": "x", "value": 0} if False else {}},
            ]
        })
        # QEMU doesn't have a native wheel axis, simulate via buttons 4/5
        btn = 4 if direction == "up" else 5
        for _ in range(min(abs(int(event.delta_y or 0)) // 15 + 1, 10)):
            self._qmp_cmd("input-send-event", {
                "events": [
                    {"type": "btn", "data": {"action": "press", "button": "left"} if False else {}},
                    {"type": "btn", "data": {"action": "press", "button": "left" if btn == 4 else "left"}},
                ]
            })

    def _send_text(self, event: InputEvent) -> None:
        """Type a string into the VM via individual key presses."""
        text = event.text if hasattr(event, 'text') else ""
        if not text and event.key:
            text = chr(event.key) if 32 <= event.key <= 126 else ""
        for char in text:
            if char in _CHAR_TO_QCODE:
                mapping = _CHAR_TO_QCODE[char]
                if isinstance(mapping, tuple):
                    _, qcode = mapping
                    self._qmp_cmd("input-send-event", {
                        "events": [
                            {"type": "key", "data": {"action": "press", "key": {"type": "qcode", "data": _qcode_name(_CHAR_TO_QCODE.get(' ', 'key_space'))}}},
                            {"type": "key", "data": {"action": "press", "key": {"type": "qcode", "data": _qcode_name(qcode)}}},
                            {"type": "key", "data": {"action": "release", "key": {"type": "qcode", "data": _qcode_name(qcode)}}},
                        ]
                    })
                else:
                    self._qmp_cmd("input-send-event", {
                        "events": [
                            {"type": "key", "data": {"action": "press", "key": {"type": "qcode", "data": _qcode_name(mapping)}}},
                            {"type": "key", "data": {"action": "release", "key": {"type": "qcode", "data": _qcode_name(mapping)}}},
                        ]
                    })

    # ── Window lifecycle ────────────────────────────────────────────────

    def resize(self, width: int, height: int) -> None:
        self._width = max(320, width)
        self._height = max(240, height)
        # QEMU doesn't support runtime resize of headless displays,
        # so we'd need to restart. For now, store the requested size.
        # A real implementation would use QEMU's QMP to change the
        # graphics device or restart with new parameters.

    def focus(self) -> None:
        pass

    def minimize(self) -> None:
        try:
            self._qmp_cmd("stop")
        except Exception:
            pass

    def close(self) -> None:
        self.stop()

    # ── QMP helpers ─────────────────────────────────────────────────────

    def _build_qemu_cmd(self) -> list[str]:
        """Build the QEMU command line.

        Starts with the user-provided qemu_argv (if any), then appends
        standard flags for QMP, VNC, and display.
        """
        cmd = self._qemu_argv[:] if self._qemu_argv else ["qemu-system-x86_64"]
        # Only add standard flags if not already specified in qemu_argv
        extra = []
        if not any("-qmp" in arg for arg in cmd):
            extra.extend(["-qmp", f"unix:{self._qmp_path},server=on,wait=off"])
        if not any(arg.startswith("-vnc") for arg in cmd):
            extra.extend(["-vnc", f":{self._vnc_display}"])
        if not any(arg.startswith("-display") for arg in cmd):
            extra.extend(["-display", "egl-headless"])
        cmd.extend(extra)
        return cmd

    def _ensure_qmp_socket_removed(self):
        try:
            Path(self._qmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    def _connect_qmp(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(self._qmp_path)
        # Read the QMP greeting
        greeting = self._qmp_recv()
        # Send qmp_capabilities
        self._qmp_send({"execute": "qmp_capabilities"})
        self._qmp_sock = sock

    def _disconnect_qmp(self):
        if self._qmp_sock:
            try:
                self._qmp_sock.close()
            except Exception:
                pass
            self._qmp_sock = None

    def _qmp_send(self, cmd: dict) -> None:
        if self._qmp_sock is None:
            raise ConnectionError("QMP not connected")
        data = json.dumps(cmd).encode("utf-8")
        self._qmp_sock.sendall(data)

    def _qmp_recv(self, timeout: float = 2.0) -> dict | None:
        if self._qmp_sock is None:
            return None
        self._qmp_sock.settimeout(timeout)
        chunks = []
        try:
            while True:
                chunk = self._qmp_sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                data = b"".join(chunks)
                # Check if we have a complete JSON object
                try:
                    return json.loads(data.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
        except socket.timeout:
            if chunks:
                try:
                    return json.loads(b"".join(chunks).decode("utf-8"))
                except json.JSONDecodeError:
                    pass
        return None

    def _qmp_cmd(self, execute: str, arguments: dict | None = None) -> dict | None:
        """Send a QMP command and return the response."""
        cmd = {"execute": execute}
        if arguments:
            cmd["arguments"] = arguments
        self._qmp_send(cmd)
        return self._qmp_recv()
