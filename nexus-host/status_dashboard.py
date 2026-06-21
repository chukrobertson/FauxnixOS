"""Status dashboard widget — network, models, uptime, startup settings."""

import os
import socket
import time
import subprocess
import winreg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QCheckBox, QScrollArea,
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
        self._refresh_startup()

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
        self._add_card(layout, "Startup", self._startup_widget())
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

    def _startup_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        # Nexus Host toggle
        host_row = QHBoxLayout()
        self._host_toggle = QCheckBox("Start Nexus Host at boot")
        self._host_toggle.setStyleSheet(
            "QCheckBox { color: #b0b0b0; font-size: 11px; spacing: 6px; }"
            "QCheckBox::indicator { width: 36px; height: 18px; border-radius: 9px; "
            "background: #333; border: 1px solid #555; }"
            "QCheckBox::indicator:checked { background: #00cc66; border-color: #00cc66; }"
            "QCheckBox::indicator:unchecked { background: #333; }"
        )
        self._host_toggle.stateChanged.connect(lambda s: self._toggle_host(s))
        host_row.addWidget(self._host_toggle)
        host_row.addStretch()
        self._host_status = QLabel("")
        self._host_status.setStyleSheet("color: #888; font-size: 9px; border: none;")
        host_row.addWidget(self._host_status)
        layout.addLayout(host_row)

        # Faux-pass provider toggle
        prov_row = QHBoxLayout()
        self._prov_toggle = QCheckBox("Start Faux-pass Provider at boot")
        self._prov_toggle.setStyleSheet(
            "QCheckBox { color: #b0b0b0; font-size: 11px; spacing: 6px; }"
            "QCheckBox::indicator { width: 36px; height: 18px; border-radius: 9px; "
            "background: #333; border: 1px solid #555; }"
            "QCheckBox::indicator:checked { background: #00cc66; border-color: #00cc66; }"
            "QCheckBox::indicator:unchecked { background: #333; }"
        )
        self._prov_toggle.stateChanged.connect(lambda s: self._toggle_provider(s))
        prov_row.addWidget(self._prov_toggle)
        prov_row.addStretch()
        self._prov_status = QLabel("")
        self._prov_status.setStyleSheet("color: #888; font-size: 9px; border: none;")
        prov_row.addWidget(self._prov_status)
        layout.addLayout(prov_row)

        return w

    def _get_run_key(self, name: str) -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except FileNotFoundError:
            return None

    def _set_run_key(self, name: str, command: str):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def _del_run_key(self, name: str):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def _toggle_host(self, state: int):
        script = os.path.join(os.path.dirname(__file__), "nexus_host.py")
        cmd = f'pythonw.exe "{script}"'
        if state:
            self._set_run_key("Fauxnix Nexus Host", cmd)
            self._host_status.setText("enabled")
            self._host_status.setStyleSheet("color: #00cc66; font-size: 9px; border: none; font-weight: bold;")
        else:
            self._del_run_key("Fauxnix Nexus Host")
            self._host_status.setText("disabled")
            self._host_status.setStyleSheet("color: #888; font-size: 9px; border: none;")

    def _toggle_provider(self, state: int):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        provider_ps1 = os.path.join(repo_root, "remote-nixos", "faux-pass", "provider", "run-nexus-provider.cmd")
        if state:
            self._set_run_key("Fauxnix Faux-pass Provider", f'cmd.exe /c "{provider_ps1}"')
            self._prov_status.setText("enabled")
            self._prov_status.setStyleSheet("color: #00cc66; font-size: 9px; border: none; font-weight: bold;")
        else:
            self._del_run_key("Fauxnix Faux-pass Provider")
            self._prov_status.setText("disabled")
            self._prov_status.setStyleSheet("color: #888; font-size: 9px; border: none;")

    def _refresh_startup(self):
        self._host_toggle.blockSignals(True)
        self._prov_toggle.blockSignals(True)

        host_val = self._get_run_key("Fauxnix Nexus Host")
        if host_val:
            self._host_toggle.setChecked(True)
            self._host_status.setText("enabled")
            self._host_status.setStyleSheet("color: #00cc66; font-size: 9px; border: none; font-weight: bold;")
        else:
            self._host_toggle.setChecked(False)
            self._host_status.setText("disabled")
            self._host_status.setStyleSheet("color: #888; font-size: 9px; border: none;")

        prov_val = self._get_run_key("Fauxnix Faux-pass Provider")
        if prov_val:
            self._prov_toggle.setChecked(True)
            self._prov_status.setText("enabled")
            self._prov_status.setStyleSheet("color: #00cc66; font-size: 9px; border: none; font-weight: bold;")
        else:
            self._prov_toggle.setChecked(False)
            self._prov_status.setText("disabled")
            self._prov_status.setStyleSheet("color: #888; font-size: 9px; border: none;")

        self._host_toggle.blockSignals(False)
        self._prov_toggle.blockSignals(False)

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

        # Startup settings
        self._refresh_startup()

        # Uptime
        elapsed = int(time.time() - self._start_time)
        h, m = divmod(elapsed // 60, 60)
        self._uptime_label.setText(f"{h}h {m}m")
