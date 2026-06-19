"""Fauxnix Node Server — runs a single node as a standalone process.

Protocol: newline-delimited JSON over Unix socket.

Canvas → Node:
  {"cmd": "create", "id": "...", "x": 100, "y": 200, "w": 280}
  {"cmd": "move", "x": 150}
  {"cmd": "resize", "w": 400}
  {"cmd": "push", "socket": 0, "data": {"text": "hello"}}
  {"cmd": "close"}

Node → Canvas:
  {"event": "ready", "type": "Clock", "id": "abc123", "w": 200, "h": 80}
  {"event": "push", "socket": 0, "data": {"text": "hello", "type": "text"}}
  {"event": "error", "msg": "..."}
"""

import sys
import os
import json
import socket
import struct
import select
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1"

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QTimer


class NodeServer:
    def __init__(self, sock_path: str, node_type: str):
        self._sock_path = sock_path
        self._node_type = node_type
        self._node = None
        self._app = None
        self._conn = None
        self._buf = b""

    def run(self):
        from fauxnix_workspace.canvas import get_node_types
        from fauxnix_workspace.nodes import node_types  # noqa

        cls = get_node_types().get(self._node_type)
        if not cls:
            self._send_error(f"Unknown node type: {self._node_type}")
            return

        self._app = QApplication(sys.argv)
        self._node = cls()

        self._connect()
        self._send_ready()

        # Forward socket pushes from node to canvas
        for i, s in enumerate(self._node._sockets):
            original_push = s.push_data
            idx = i
            def _make_forwarder(sock, orig, si):
                def _forward(data):
                    orig(data)
                    try:
                        msg = json.dumps({"event": "push", "socket": si, "data": data})
                        if self._conn:
                            self._conn.sendall((msg + "\n").encode("utf-8"))
                    except Exception:
                        pass
                return _forward
            s.push_data = _make_forwarder(s, original_push, i)

        # Poll for canvas commands
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(50)

        self._app.exec()

    def _connect(self):
        try:
            os.unlink(self._sock_path)
        except OSError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self._sock_path)
        server.listen(1)
        server.setblocking(False)
        self._server = server

    def _poll(self):
        if self._server and not self._conn:
            try:
                self._conn, _ = self._server.accept()
                self._conn.setblocking(False)
            except BlockingIOError:
                pass

        if self._conn:
            try:
                data = self._conn.recv(4096)
                if data:
                    self._buf += data
                    while b"\n" in self._buf:
                        line, self._buf = self._buf.split(b"\n", 1)
                        self._handle(json.loads(line.decode("utf-8")))
                else:
                    self._conn.close()
                    self._conn = None
                    self._buf = b""
            except BlockingIOError:
                pass
            except Exception:
                self._conn = None
                self._buf = b""

    def _handle(self, msg: dict):
        cmd = msg.get("cmd", "")
        try:
            if cmd == "move":
                self._node.widget.move(msg.get("x", 0), msg.get("y", 0))
            elif cmd == "resize":
                self._node.set_node_width(msg.get("w", self._node._node_width))
            elif cmd == "push":
                si = msg.get("socket", 0)
                if si < len(self._node._sockets):
                    self._node.on_data_received(self._node._sockets[si], msg.get("data", {}))
            elif cmd == "close":
                self._shutdown()
        except Exception as e:
            self._send_error(str(e))

    def _send_ready(self):
        self._send({"event": "ready", "type": self._node_type,
                     "id": self._node._node_id, "w": self._node._node_width,
                     "h": self._node.widget.height() if self._node.widget else 80})

    def _send(self, msg: dict):
        if self._conn:
            try:
                self._conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            except Exception:
                pass

    def _send_error(self, msg: str):
        self._send({"event": "error", "msg": msg})

    def _shutdown(self):
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._server:
            self._server.close()
            self._server = None
        try:
            os.unlink(self._sock_path)
        except OSError:
            pass
        if self._app:
            self._app.quit()


def main():
    if len(sys.argv) < 3:
        print("Usage: fauxnix-node <socket> <node_type>")
        sys.exit(1)
    sock_path = sys.argv[1]
    node_type = sys.argv[2]
    server = NodeServer(sock_path, node_type)
    server.run()


if __name__ == "__main__":
    main()
