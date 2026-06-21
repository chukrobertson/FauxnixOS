"""Status dashboard widget — network, models, uptime, startup settings."""

import os
import socket
import time
import subprocess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QCheckBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

import json
import urllib.request

_NW = subprocess.CREATE_NO_WINDOW  # Prevents console allocation entirely

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

        # Faux-pass provider — bundled with host toggle
        prov_row = QHBoxLayout()
        prov_label = QLabel("  + Faux-pass Provider (bundled)")
        prov_label.setStyleSheet("color: #666; font-size: 10px;")
        prov_row.addWidget(prov_label)
        prov_row.addStretch()
        self._prov_status = QLabel("")
        self._prov_status.setStyleSheet("color: #888; font-size: 9px; border: none;")
        prov_row.addWidget(self._prov_status)
        layout.addLayout(prov_row)

        return w

    def _task_exists(self, name: str) -> bool:
        try:
            import subprocess
            r = subprocess.run(["schtasks", "/Query", "/TN", name, "/V", "/FO", "CSV"],
                               capture_output=True, text=True, timeout=5,
                               creationflags=_NW)
            return r.returncode == 0
        except Exception:
            return False

    def _toggle_host(self, state: int):
        vbs = os.path.join(os.path.dirname(__file__), "nexus-boot.vbs")
        if state:
            subprocess.run([
                "powershell.exe", "-Command",
                f"Register-ScheduledTask -TaskName 'Fauxnix Nexus' -Action "
                f"(New-ScheduledTaskAction -Execute 'wscript.exe' -Argument 'E:\\Fauxnix\\nexus-host\\nexus-boot.vbs //Nologo' -WorkingDirectory 'E:\\Fauxnix\\nexus-host') "
                f"-Trigger (New-ScheduledTaskTrigger -AtLogOn) "
                f"-Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable) "
                f"-Principal (New-ScheduledTaskPrincipal -UserId '$env:USERDOMAIN\\$env:USERNAME' -LogonType Interactive -RunLevel Limited) -Force"
            ], capture_output=True, timeout=15, creationflags=_NW)
            self._host_status.setText("enabled")
            self._host_status.setStyleSheet("color: #00cc66; font-size: 9px; border: none; font-weight: bold;")
        else:
            subprocess.run([
                "powershell.exe", "-Command",
                "Unregister-ScheduledTask -TaskName 'Fauxnix Nexus' -Confirm:$false"
            ], capture_output=True, timeout=15, creationflags=_NW)
            self._host_status.setText("disabled")
            self._host_status.setStyleSheet("color: #888; font-size: 9px; border: none;")

    def _toggle_provider(self, state: int):
        pass  # Provider is bundled in the single VBS task with the host

    def _refresh_startup(self):
        self._host_toggle.blockSignals(True)

        ok = self._task_exists("Fauxnix Nexus")
        self._host_toggle.setChecked(ok)
        self._host_status.setText("enabled" if ok else "disabled")
        if ok:
            self._host_status.setStyleSheet("color: #00cc66; font-size: 9px; border: none; font-weight: bold;")
            self._prov_status.setText("bundled")
            self._prov_status.setStyleSheet("color: #666; font-size: 9px; border: none;")
        else:
            self._host_status.setStyleSheet("color: #888; font-size: 9px; border: none;")
            self._prov_status.setText("disabled")
            self._prov_status.setStyleSheet("color: #888; font-size: 9px; border: none;")

        self._host_toggle.blockSignals(False)

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
        # Network — local IP via UDP socket (no subprocess)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("100.100.100.100", 1))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "unknown"
        self._ip_label.setText(f"IP: {ip}")

        # Tailscale — use CLI with CREATE_NO_WINDOW (no console)
        ts_ip = "offline"
        ts_online = 0
        try:
            ts_out = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=3,
                creationflags=_NW,
            )
            if ts_out.returncode == 0 and ts_out.stdout.strip():
                ts = json.loads(ts_out.stdout)
                self_ip = ts.get("Self", {})
                ts_ip = (self_ip.get("TailscaleIPs") or [None])[0] or "unknown"
                self._tailscale_label.setText(f"Tailscale: {ts_ip}")
                peer_list = ts.get("Peer", {})
                ts_online = sum(
                    1 for p in peer_list.values()
                    if p.get("Online", False) and "linux" in p.get("OS", "").lower()
                )
            else:
                self._tailscale_label.setText("Tailscale: offline")
        except Exception:
            self._tailscale_label.setText("Tailscale: offline")
        self._connections_label.setText(f"Fauxnix nodes: {ts_online} online")

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
