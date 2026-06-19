"""Status dashboard widget — network, models, uptime."""

import socket
import time
import subprocess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ollama_client import get_models, ollama_health


class StatusDashboard(QWidget):
    """Network stats, installed models, connected nodes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #0d0e12;")
        self._start_time = time.time()
        self._build_ui()
        self._refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(10000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title = QLabel("Nexus Host — Status")
        title.setStyleSheet("color: #ff7800; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # Cards
        self._add_card(layout, "Network", self._network_widget())
        self._add_card(layout, "Ollama Models", self._models_widget())
        self._add_card(layout, "Uptime", self._uptime_widget())

        layout.addStretch()

    def _add_card(self, parent, title: str, widget: QWidget):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #141518; border: 1px solid #2a2d33; border-radius: 6px; }"
        )
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 8, 10, 8)

        lbl = QLabel(title)
        lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        fl.addWidget(lbl)
        fl.addWidget(widget)
        parent.addWidget(frame)

    def _network_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 4, 0, 0)

        self._ip_label = QLabel("IP: detecting...")
        self._ip_label.setStyleSheet("color: #b0b0b0; font-size: 11px; border: none;")
        layout.addWidget(self._ip_label)

        self._tailscale_label = QLabel("Tailscale: detecting...")
        self._tailscale_label.setStyleSheet("color: #b0b0b0; font-size: 11px; border: none;")
        layout.addWidget(self._tailscale_label)

        self._connections_label = QLabel("Fauxnix nodes: —")
        self._connections_label.setStyleSheet("color: #00c8ff; font-size: 11px; border: none;")
        layout.addWidget(self._connections_label)

        return w

    def _models_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 4, 0, 0)

        self._models_list = QLabel("Loading...")
        self._models_list.setStyleSheet("color: #b0b0b0; font-size: 11px; border: none;")
        self._models_list.setWordWrap(True)
        layout.addWidget(self._models_list)

        self._ollama_status = QLabel("Ollama: checking...")
        self._ollama_status.setStyleSheet("color: #888; font-size: 10px; border: none;")
        layout.addWidget(self._ollama_status)

        return w

    def _uptime_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 4, 0, 0)

        self._uptime_label = QLabel("0m")
        self._uptime_label.setStyleSheet("color: #b0b0b0; font-size: 14px; font-weight: bold; border: none;")
        layout.addWidget(self._uptime_label)

        return w

    def _refresh(self):
        # Network
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("100.100.100.100", 1))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "unknown"
        self._ip_label.setText(f"IP: {ip}")

        try:
            ts_ip = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            ts_ip = "offline"
        self._tailscale_label.setText(f"Tailscale: {ts_ip}")

        try:
            r = subprocess.run(
                ["tailscale", "status"],
                capture_output=True, text=True, timeout=5,
            )
            online_count = 0
            for line in r.stdout.strip().split("\n"):
                if line.strip() and "offline" not in line and "linux" in line.lower():
                    online_count += 1
            self._connections_label.setText(f"Fauxnix nodes: {online_count} online")
        except Exception:
            self._connections_label.setText("Fauxnix nodes: —")

        # Models
        health = ollama_health()
        if health:
            self._ollama_status.setText("Ollama: online")
            self._ollama_status.setStyleSheet("color: #00cc66; font-size: 10px; border: none;")
            models = get_models()
            if models:
                self._models_list.setText("\n".join(f"  \u2022 {m}" for m in models[:10]))
            else:
                self._models_list.setText("No models found")
        else:
            self._ollama_status.setText("Ollama: offline")
            self._ollama_status.setStyleSheet("color: #ff4444; font-size: 10px; border: none;")
            self._models_list.setText("Ollama not reachable")

        # Uptime
        elapsed = int(time.time() - self._start_time)
        h, m = divmod(elapsed // 60, 60)
        self._uptime_label.setText(f"{h}h {m}m")
