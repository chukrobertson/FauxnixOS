"""Node Process Manager — spawns node processes and proxies their state to the canvas.

Each node runs as fauxnix-node <socket> <type>. The canvas spawns the process,
connects via Unix socket, sends commands, receives state updates.
"""

import json
import os
import socket
import subprocess
import tempfile
import threading
from PyQt6.QtCore import QTimer, QObject, pyqtSignal


class NodeProcess(QObject):
    """Manages a single node process — spawn, connect, command, and listen."""
    ready = pyqtSignal(dict)
    push = pyqtSignal(int, dict)
    error = pyqtSignal(str)
    died = pyqtSignal()

    def __init__(self, node_type: str, parent=None):
        super().__init__(parent)
        self._node_type = node_type
        self._sock_path = f"/tmp/fauxnix-node-{os.getpid()}-{id(self)}.sock"
        self._process = None
        self._conn = None
        self._buf = b""
        self._alive = False

    def start(self):
        try:
            os.unlink(self._sock_path)
        except OSError:
            pass

        self._process = subprocess.Popen(
            ["fauxnix-node", self._sock_path, self._node_type],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # Connect in background
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._try_connect)
        self._timer.start(100)

    def _try_connect(self):
        if self._conn:
            return
        try:
            self._conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._conn.connect(self._sock_path)
            self._conn.setblocking(False)
            self._alive = True
            self._timer.setInterval(50)
            # Switch to polling for messages
            self._timer.timeout.disconnect()
            self._timer.timeout.connect(self._poll)
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        except Exception as e:
            self.error.emit(str(e))
            self._timer.stop()

    def _poll(self):
        if not self._conn:
            return
        try:
            data = self._conn.recv(4096)
            if data:
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    self._handle(json.loads(line.decode("utf-8")))
            else:
                self._on_dead()
        except BlockingIOError:
            pass
        except Exception:
            pass

        if self._process and self._process.poll() is not None:
            self._on_dead()

    def _handle(self, msg: dict):
        event = msg.get("event", "")
        if event == "ready":
            self.ready.emit(msg)
        elif event == "push":
            self.push.emit(msg.get("socket", 0), msg.get("data", {}))
        elif event == "error":
            self.error.emit(msg.get("msg", ""))

    def send(self, cmd: dict):
        if self._conn and self._alive:
            try:
                self._conn.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            except Exception:
                self._on_dead()

    def move(self, x: int, y: int):
        self.send({"cmd": "move", "x": x, "y": y})

    def resize(self, w: int):
        self.send({"cmd": "resize", "w": w})

    def push_data(self, socket_idx: int, data: dict):
        self.send({"cmd": "push", "socket": socket_idx, "data": data})

    def close(self):
        self.alive = False
        self.send({"cmd": "close"})
        self._cleanup()

    def _on_dead(self):
        self._alive = False
        self.died.emit()
        self._cleanup()

    def _cleanup(self):
        if self._timer:
            self._timer.stop()
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                pass
            self._process = None
        try:
            os.unlink(self._sock_path)
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        return self._alive


class NodeProcessHost:
    """Canvas-side host for a node process. Shows a placeholder card on the canvas.

    Usage:
        host = NodeProcessHost("Clock", canvas_widget)
        host.spawn()
        # Later: host.move(100, 200)
        # When process sends push events: host.push.connect(handler)
    """

    CARD_W = 200
    CARD_H = 80

    def __init__(self, node_type: str, canvas_widget):
        from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
        from PyQt6.QtCore import Qt

        self._node_type = node_type
        self._canvas = canvas_widget
        self._process = None
        self._node_id = None
        self._node_w = 200
        self._node_h = 80
        self._sockets = []

        # Placeholder card widget
        self.widget = QWidget(canvas_widget)
        self.widget.setFixedSize(self.CARD_W, self.CARD_H)
        self.widget.setStyleSheet("background: #141518; border: 1px solid #2a2d33; border-radius: 6px;")
        self.widget.setCursor(Qt.CursorShape.OpenHandCursor)

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(8, 6, 8, 6)

        self._title_label = QLabel(node_type)
        self._title_label.setStyleSheet("color: #d4d4d4; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        layout.addWidget(self._title_label)

        self._status_label = QLabel("Starting...")
        self._status_label.setStyleSheet("color: #888; font-size: 10px; border: none; background: transparent;")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self.widget.hide()

    def spawn(self):
        if self._process:
            return
        self._process = NodeProcess(self._node_type)
        self._process.ready.connect(self._on_ready)
        self._process.push.connect(self._on_push)
        self._process.error.connect(self._on_error)
        self._process.died.connect(self._on_died)
        self._process.start()
        self._status_label.setText("Connecting...")
        self.widget.show()

    def move(self, x: int, y: int):
        self.widget.move(x, y)
        if self._process and self._process.alive:
            self._process.move(x, y)

    def close(self):
        if self._process:
            self._process.close()
            self._process = None
        self.widget.setParent(None)

    def x(self): return self.widget.x()
    def y(self): return self.widget.y()

    def _on_ready(self, data: dict):
        self._node_id = data.get("id", "")
        self._node_w = data.get("w", self.CARD_W)
        self._node_h = data.get("h", self.CARD_H)
        self.widget.setFixedSize(max(self._node_w, 180), max(self._node_h, 60))
        self._status_label.setText(f"Ready — {self._node_type}")
        self._status_label.setStyleSheet("color: #00cc66; font-size: 10px; border: none; background: transparent;")

    def _on_push(self, socket_idx: int, data: dict):
        # Forward push events to connected canvas sockets
        pass  # Wires will be handled by canvas-level routing

    def _on_error(self, msg: str):
        self._status_label.setText(f"Error: {msg}")
        self._status_label.setStyleSheet("color: #ff4444; font-size: 10px; border: none; background: transparent;")

    def _on_died(self):
        self._status_label.setText("Offline")
        self._status_label.setStyleSheet("color: #ff4444; font-size: 10px; border: none; background: transparent;")
        self._process = None
        # Auto-restart after 2 seconds
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, self.spawn)
