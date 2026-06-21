"""Nexus Coder — FauxnixOS builder pipeline.

Stages: Plan -> Scrutinize -> Generate Diffs -> Snapshot -> Apply -> Verify -> Finalize
Model stages call Ollama. Action stages touch the filesystem.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFrame, QScrollArea, QCheckBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QListWidget, QListWidgetItem,
    QLineEdit,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

from ollama_client import OLLAMA_URL

CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Fauxnix")
CONFIG_FILE = os.path.join(CONFIG_DIR, "coder-config.json")
SNAPSHOT_DIR = os.path.join(CONFIG_DIR, "coder-snapshots")

PROJECT_ROOT = r"E:\Fauxnix"

DEFAULT_STAGES = [
    {"id": "planner", "label": "1. Plan", "model": "qwen3.5:0.8b", "color": "#6b5b95", "num_ctx": 8192, "temperature": 0.7, "use_kb": True, "kind": "model", "prompt_tpl": "You are a FauxnixOS software architect. Understand the task below and plan which files to change. Output a numbered plan.\n\nTask:\n{input}"},
    {"id": "scrutinizer", "label": "2. Scrutinize", "model": "huihui_ai/huihui-moe-abliterated:1.5b", "color": "#d64161", "num_ctx": 8192, "temperature": 0.3, "use_kb": True, "kind": "model", "prompt_tpl": "You are a senior code reviewer. Identify gaps, risks, and edge cases in the plan below.\n\nPlan:\n{input}"},
    {"id": "diff_generator", "label": "3. Generate Diffs", "model": "granite-code:20b", "color": "#00b4d8", "num_ctx": 16384, "temperature": 0.2, "use_kb": True, "kind": "model", "prompt_tpl": "You are a senior developer. Generate unified diffs for the changes described below. Output ONLY the diff (---/+++ format).\n\nInput:\n{input}"},
    {"id": "snapshot", "label": "4. Snapshot", "model": "", "color": "#ffaa00", "num_ctx": 4096, "temperature": 0.5, "use_kb": False, "kind": "action", "prompt_tpl": ""},
    {"id": "apply", "label": "5. Apply", "model": "", "color": "#ff6600", "num_ctx": 4096, "temperature": 0.5, "use_kb": False, "kind": "action", "prompt_tpl": ""},
    {"id": "verify", "label": "6. Verify", "model": "minicpm-v4.6:latest", "color": "#f9c74f", "num_ctx": 8192, "temperature": 0.3, "use_kb": False, "kind": "verify", "prompt_tpl": "Review the verification output below. Check for errors, warnings, and test failures. Give a CLEAR PASS/FAIL verdict.\n\nVerification output:\n{input}"},
    {"id": "finalizer", "label": "7. Final Review", "model": "qwen3.5:0.8b", "color": "#43aa8b", "num_ctx": 8192, "temperature": 0.5, "use_kb": True, "kind": "model", "prompt_tpl": "You are a project lead. Review the full pipeline output: plan, scrutiny, diffs, snapshot, apply result, verification. Give a CLEAR PASS/FAIL/NEEDS_REVISION verdict.\n\nFull output:\n{input}"},
]


def load_config() -> tuple[list[dict], list[str], dict]:
    defaults = [dict(s) for s in DEFAULT_STAGES]
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            stages = data.get("stages", defaults)
            kb = data.get("knowledge_base", [])
            project = data.get("project", {"root": PROJECT_ROOT, "verify_cmd": "", "auto_commit": False})
            if isinstance(stages, list) and len(stages) == len(DEFAULT_STAGES):
                return stages, kb, project
        if isinstance(data, list) and len(data) == len(DEFAULT_STAGES):
            return data, [], {"root": PROJECT_ROOT, "verify_cmd": "", "auto_commit": False}
    except Exception:
        pass
    return defaults, [], {"root": PROJECT_ROOT, "verify_cmd": "", "auto_commit": False}


def save_config(stages: list[dict], kb: list[str], project: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"stages": stages, "knowledge_base": kb, "project": project}, f, indent=2)


def read_kb_files(paths: list[str]) -> str:
    parts = []
    for p in paths:
        p = p.strip()
        if not p:
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                parts.append(f"--- {p} ---\n{f.read()}")
        except Exception as e:
            parts.append(f"--- {p} ---\n(unreadable: {e})")
    return "\n\n".join(parts) if parts else ""


def _fetch_models() -> list[str]:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        return []


def _parse_file_list(text: str) -> list[str]:
    files = re.findall(r'(?:^|\n)(?:[-*]\s*)?`([^`]+)`|(?:^|\n)(?:[-*]\s*)?\*\*([^*]+)\*\*|(?:^|\n)(?:\d+\.\s*)?([^\n]+\.(?:py|nix|json|md|toml|cfg|ini|sh|ps1|bat|cmd|yaml|yml|conf))', text)
    result = set()
    for match in files:
        for g in match:
            if g and g.strip():
                result.add(g.strip().rstrip("."))
    return list(result)


def _extract_diffs(text: str) -> str:
    lines = text.split("\n")
    diff_lines = []
    in_diff = False
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("diff --git"):
            in_diff = True
        if in_diff:
            diff_lines.append(line)
    if diff_lines:
        return "\n".join(diff_lines)
    return text


def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 60, input_text: str | None = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, input=input_text, creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


class StageSignals(QObject):
    running = pyqtSignal(object)
    done = pyqtSignal(object, str)
    error = pyqtSignal(object, str)
    detail = pyqtSignal(object, str)


class StageCard(QFrame):
    def __init__(self, stage_def: dict, models: list[str], parent=None):
        super().__init__(parent)
        self.stage_id = stage_def["id"]
        self.color = stage_def["color"]
        self.kind = stage_def.get("kind", "model")
        self.prompt_tpl = stage_def.get("prompt_tpl", "")
        self.output_text = ""
        self._config_mode = False
        self._build_ui(stage_def, models)

    def _build_ui(self, sd: dict, models: list[str]):
        self.setStyleSheet("StageCard { background: #141518; border: 1px solid #2a2d33; border-radius: 6px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        header = QHBoxLayout()
        self._label = QLabel(sd["label"])
        self._label.setStyleSheet(f"color: {self.color}; font-size: 11px; font-weight: bold;")
        header.addWidget(self._label)

        kind_badge = QLabel(f"[{self.kind}]")
        kind_badge.setStyleSheet(f"color: {self.color}; font-size: 8px; padding: 1px 4px; border: 1px solid {self.color}; border-radius: 2px;")
        header.addWidget(kind_badge)

        header.addStretch()

        self._badge = QLabel(sd.get("model", "") or "(action)")
        self._badge.setStyleSheet(f"background: {self.color}; color: #080909; font-size: 9px; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
        header.addWidget(self._badge)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(160)
        self._combo.setStyleSheet("QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 4px; font-size: 10px; } QComboBox::drop-down { border: none; } QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; selection-background-color: #ff7800; }")
        if models:
            self._combo.addItems(models)
        idx = self._combo.findText(sd.get("model", ""))
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.currentTextChanged.connect(self._badge.setText)
        self._combo.setVisible(self.kind == "model")
        header.addWidget(self._combo)

        self._status = QLabel("waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        header.addWidget(self._status)
        layout.addLayout(header)

        self._config_row = QHBoxLayout()
        self._use_kb_cb = QCheckBox("Use KB")
        self._use_kb_cb.setChecked(sd.get("use_kb", True))
        self._use_kb_cb.setStyleSheet("QCheckBox { color: #888; font-size: 9px; spacing: 3px; }")
        self._use_kb_cb.setVisible(self.kind == "model")
        self._config_row.addWidget(self._use_kb_cb)

        self._config_row.addWidget(QLabel("Ctx:"))
        self._ctx_spin = QSpinBox()
        self._ctx_spin.setRange(2048, 65536); self._ctx_spin.setSingleStep(2048); self._ctx_spin.setValue(sd.get("num_ctx", 8192))
        self._ctx_spin.setStyleSheet("QSpinBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 2px; padding: 1px 3px; font-size: 9px; max-width: 70px; }")
        self._config_row.addWidget(self._ctx_spin)

        self._config_row.addWidget(QLabel("Temp:"))
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0); self._temp_spin.setSingleStep(0.1); self._temp_spin.setValue(sd.get("temperature", 0.7))
        self._temp_spin.setStyleSheet("QDoubleSpinBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 2px; padding: 1px 3px; font-size: 9px; max-width: 60px; }")
        self._temp_spin.setVisible(self.kind == "model")
        self._config_row.addWidget(self._temp_spin)

        self._config_row.addStretch()
        self._config_row_widget = QWidget()
        self._config_row_widget.setLayout(self._config_row)
        self._config_row_widget.setStyleSheet("background: transparent;")
        self._config_row_widget.hide()
        layout.addWidget(self._config_row_widget)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(90)
        self._output.setStyleSheet("QTextEdit { background: #0d0e12; color: #b0b0b0; border: 1px solid #1e1e24; border-radius: 4px; padding: 4px; font-size: 10px; }")
        layout.addWidget(self._output)

    @property
    def model(self) -> str:
        return self._combo.currentText() if self._combo.isVisible() else self._badge.text()

    def set_config_mode(self, enabled: bool):
        self._config_mode = enabled
        combo_visible = enabled and self.kind == "model"
        self._badge.setVisible(not combo_visible)
        self._combo.setVisible(combo_visible)
        self._config_row_widget.setVisible(enabled)
        self._use_kb_cb.setVisible(enabled and self.kind == "model")

    def get_config(self) -> dict:
        return {
            "model": self.model,
            "use_kb": self._use_kb_cb.isChecked(),
            "num_ctx": self._ctx_spin.value(),
            "temperature": self._temp_spin.value(),
        }

    def set_detail(self, text: str):
        self._output.clear()
        self._output.append(text[:500])
        if len(text) > 500:
            self._output.append(f"\n... ({len(text)} total chars)")

    def set_running(self):
        self._status.setText("running...")
        self._status.setStyleSheet("color: #00c8ff; font-size: 10px; font-weight: bold;")
        self._output.clear()

    def set_done(self, text: str):
        self.output_text = text
        self._status.setText("done")
        self._status.setStyleSheet("color: #00cc66; font-size: 10px; font-weight: bold;")
        self._output.clear()
        self._output.append(text[:500])
        if len(text) > 500:
            self._output.append(f"\n... ({len(text)} total chars)")

    def set_error(self, err: str):
        self._status.setText("error")
        self._status.setStyleSheet("color: #ff4444; font-size: 10px; font-weight: bold;")
        self._output.clear()
        self._output.append(err)

    def set_skipped(self):
        self._status.setText("skipped")
        self._status.setStyleSheet("color: #666; font-size: 10px;")

    def clear(self):
        self.output_text = ""
        self._status.setText("waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        self._output.clear()


class CoderWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: list[StageCard] = []
        self._stage_defs: list[dict] = []
        self._kb_paths: list[str] = []
        self._project_cfg: dict = {}
        self._models: list[str] = []
        self._running = False
        self._config_mode = False
        self._cancel_flag = threading.Event()
        self._stage_signals = StageSignals()
        self._stage_signals.running.connect(self._on_stage_running)
        self._stage_signals.done.connect(self._on_stage_done)
        self._stage_signals.error.connect(self._on_stage_error)
        self._stage_signals.detail.connect(lambda s, t: s.set_detail(t))
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("background: #0d0e12;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Nexus Coder")
        title.setStyleSheet("color: #ff7800; font-size: 14px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self._config_btn = QPushButton("Configure")
        self._config_btn.setCheckable(True)
        self._config_btn.setStyleSheet("QPushButton { background: #1c1e23; color: #b0b0b0; border: 1px solid #2a2d33; border-radius: 4px; padding: 5px 12px; font-size: 10px; } QPushButton:hover { background: #2a2d33; } QPushButton:checked { background: #ff7800; color: #080909; }")
        self._config_btn.toggled.connect(self._toggle_config)
        header.addWidget(self._config_btn)

        self._run_btn = QPushButton("Build")
        self._run_btn.setStyleSheet("QPushButton { background: #00cc66; color: #080909; border: none; border-radius: 4px; padding: 5px 14px; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #00e673; } QPushButton:disabled { background: #333; color: #666; }")
        self._run_btn.clicked.connect(self._run_pipeline)
        header.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet("QPushButton { background: #d64161; color: #fff; border: none; border-radius: 4px; padding: 5px 14px; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #e05575; } QPushButton:disabled { background: #333; color: #666; }")
        self._cancel_btn.clicked.connect(self._cancel_pipeline)
        self._cancel_btn.setEnabled(False)
        header.addWidget(self._cancel_btn)
        layout.addLayout(header)

        layout.addWidget(QLabel("Coding Task:"))
        self._task_input = QTextEdit()
        self._task_input.setPlaceholderText("Describe what to build...")
        self._task_input.setMaximumHeight(60)
        self._task_input.setStyleSheet("QTextEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 6px; padding: 8px; font-size: 12px; } QTextEdit:focus { border-color: #ff7800; }")
        layout.addWidget(self._task_input)

        self._pipeline_status = QLabel("")
        self._pipeline_status.setStyleSheet("color: #888; font-size: 10px; font-weight: bold;")
        layout.addWidget(self._pipeline_status)

        self._kb_label = QLabel("")
        self._kb_label.setStyleSheet("color: #666; font-size: 9px;")
        layout.addWidget(self._kb_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollBar:vertical { width: 6px; background: #0d0e12; } QScrollBar::handle:vertical { background: #2a2d33; border-radius: 3px; }")
        self._stages_widget = QWidget()
        self._stages_widget.setStyleSheet("background: transparent;")
        self._stages_layout = QVBoxLayout(self._stages_widget)
        self._stages_layout.setContentsMargins(0, 0, 0, 0)
        self._stages_layout.setSpacing(4)

        self._stage_defs, self._kb_paths, self._project_cfg = load_config()
        self._rebuild_stages()
        self._update_kb_label()
        self._scroll.setWidget(self._stages_widget)
        layout.addWidget(self._scroll, 1)

        self._kb_editor = self._build_kb_editor()
        self._project_editor = self._build_project_editor()
        layout.addWidget(self._kb_editor)
        layout.addWidget(self._project_editor)

        self._fetch_models_async()

    def _build_kb_editor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(4)

        h = QHBoxLayout()
        h.addWidget(QLabel("Knowledge Base Files:"))
        h.addStretch()
        btn = QPushButton("+ Add File")
        btn.setStyleSheet("QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; border-radius: 3px; padding: 2px 8px; font-size: 9px; } QPushButton:hover { background: #00c8ff; color: #080909; }")
        btn.clicked.connect(self._add_kb_file)
        h.addWidget(btn)
        btn2 = QPushButton("Browse...")
        btn2.setStyleSheet("QPushButton { background: #1c1e23; color: #b0b0b0; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 8px; font-size: 9px; } QPushButton:hover { background: #2a2d33; }")
        btn2.clicked.connect(self._browse_kb_file)
        h.addWidget(btn2)
        vl.addLayout(h)

        self._kb_list = QListWidget()
        self._kb_list.setStyleSheet("QListWidget { background: #0d0e12; color: #b0b0b0; border: 1px solid #2a2d33; border-radius: 4px; font-size: 9px; } QListWidget::item { padding: 2px 4px; }")
        self._kb_list.setMaximumHeight(100)
        vl.addWidget(self._kb_list)

        h2 = QHBoxLayout()
        btn3 = QPushButton("Remove Selected")
        btn3.setStyleSheet("QPushButton { background: #d64161; color: #fff; border: none; border-radius: 3px; padding: 2px 8px; font-size: 9px; } QPushButton:hover { background: #e05575; }")
        btn3.clicked.connect(self._remove_kb_file)
        h2.addWidget(btn3); h2.addStretch()
        vl.addLayout(h2)
        w.hide()
        return w

    def _build_project_editor(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 4, 0, 0)
        vl.setSpacing(4)

        vl.addWidget(QLabel("Project Settings:"))
        root_row = QHBoxLayout()
        root_row.addWidget(QLabel("Root:"))
        self._root_edit = QLineEdit(self._project_cfg.get("root", PROJECT_ROOT))
        self._root_edit.setStyleSheet("QLineEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 6px; font-size: 10px; }")
        root_row.addWidget(self._root_edit)
        browse_root = QPushButton("Browse...")
        browse_root.setStyleSheet("QPushButton { background: #1c1e23; color: #b0b0b0; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 8px; font-size: 9px; }")
        browse_root.clicked.connect(self._browse_root)
        root_row.addWidget(browse_root)
        vl.addLayout(root_row)

        verify_row = QHBoxLayout()
        verify_row.addWidget(QLabel("Verify cmd:"))
        self._verify_edit = QLineEdit(self._project_cfg.get("verify_cmd", "python -m compileall . 2>&1"))
        self._verify_edit.setStyleSheet("QLineEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 6px; font-size: 10px; }")
        verify_row.addWidget(self._verify_edit)
        vl.addLayout(verify_row)

        commit_row = QHBoxLayout()
        self._auto_commit_cb = QCheckBox("Auto-commit after apply")
        self._auto_commit_cb.setChecked(self._project_cfg.get("auto_commit", False))
        self._auto_commit_cb.setStyleSheet("QCheckBox { color: #b0b0b0; font-size: 10px; }")
        commit_row.addWidget(self._auto_commit_cb)
        commit_row.addStretch()
        vl.addLayout(commit_row)

        w.hide()
        return w

    def _update_kb_label(self):
        if self._kb_paths:
            self._kb_label.setText(f"Knowledge Base: {len(self._kb_paths)} file(s)")
            self._kb_label.setStyleSheet("color: #00c8ff; font-size: 9px;")
        else:
            self._kb_label.setText("")

    def _populate_kb_list(self):
        self._kb_list.clear()
        for p in self._kb_paths:
            self._kb_list.addItem(QListWidgetItem(p))

    def _add_kb_file(self):
        from PyQt6.QtWidgets import QInputDialog
        path, ok = QInputDialog.getText(self, "Add File", "File path:")
        if ok and path.strip():
            self._kb_paths.append(os.path.normpath(path.strip()))
            self._populate_kb_list()
            self._update_kb_label()

    def _browse_kb_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Knowledge Base File")
        if path:
            self._kb_paths.append(path)
            self._populate_kb_list()
            self._update_kb_label()

    def _remove_kb_file(self):
        row = self._kb_list.currentRow()
        if row >= 0 and row < len(self._kb_paths):
            del self._kb_paths[row]
            self._kb_list.takeItem(row)
            self._update_kb_label()

    def _browse_root(self):
        path = QFileDialog.getExistingDirectory(self, "Select Project Root", self._root_edit.text())
        if path:
            self._root_edit.setText(path)

    def _on_stage_running(self, stage: StageCard):
        stage.set_running()
        self._pipeline_status.setText(f"Running: {stage._label.text()}")
        self._pipeline_status.setStyleSheet("color: #00c8ff; font-size: 10px; font-weight: bold;")

    def _on_stage_done(self, stage: StageCard, text: str):
        stage.set_done(text)
        self._pipeline_status.setText(f"Done: {stage._label.text()}")
        self._pipeline_status.setStyleSheet("color: #00cc66; font-size: 10px; font-weight: bold;")
        QTimer.singleShot(50, lambda: self._scroll.ensureWidgetVisible(stage, 0, 0))

    def _on_stage_error(self, stage: StageCard, err: str):
        stage.set_error(err)
        self._pipeline_status.setText(f"Error: {stage._label.text()} - {err[:80]}")
        self._pipeline_status.setStyleSheet("color: #ff4444; font-size: 10px; font-weight: bold;")
        QTimer.singleShot(50, lambda: self._scroll.ensureWidgetVisible(stage, 0, 0))

    def _fetch_models_async(self):
        def fetch():
            self._models = _fetch_models()
            QTimer.singleShot(0, self._refresh_combos)
        threading.Thread(target=fetch, daemon=True).start()

    def _refresh_combos(self):
        for card in self._stages:
            if card.kind != "model":
                continue
            current = card._combo.currentText() or card._badge.text()
            card._combo.blockSignals(True)
            card._combo.clear()
            if self._models:
                card._combo.addItems(self._models)
            idx = card._combo.findText(current)
            if idx >= 0:
                card._combo.setCurrentIndex(idx)
            elif self._models:
                card._combo.setCurrentIndex(0)
            card._combo.blockSignals(False)

    def _rebuild_stages(self):
        for card in self._stages:
            self._stages_layout.removeWidget(card)
            card.setParent(None)
        self._stages.clear()
        for sd in self._stage_defs:
            card = StageCard(sd, self._models)
            self._stages.append(card)
            self._stages_layout.addWidget(card)
        self._stages_layout.addStretch()

    def _toggle_config(self, checked: bool):
        self._config_mode = checked
        self._config_btn.setText("Done" if checked else "Configure")
        self._run_btn.setEnabled(not checked)
        self._kb_editor.setVisible(checked)
        self._project_editor.setVisible(checked)
        if checked:
            self._fetch_models_async()
            self._populate_kb_list()
        for card in self._stages:
            card.set_config_mode(checked)
        if not checked:
            self._save_config()

    def _save_config(self):
        for i, card in enumerate(self._stages):
            if i < len(self._stage_defs) and card.kind == "model":
                self._stage_defs[i].update(card.get_config())
        project = {
            "root": self._root_edit.text(),
            "verify_cmd": self._verify_edit.text(),
            "auto_commit": self._auto_commit_cb.isChecked(),
        }
        save_config(self._stage_defs, self._kb_paths, project)
        self._project_cfg = project

    def _query_model(self, model: str, prompt: str, ctx: int, temp: float, timeout: int = 180) -> str:
        body = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": 4096, "num_ctx": ctx, "temperature": temp}}).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "").strip()

    def _run_stage_model(self, stage: StageCard, prompt: str, model: str, ctx: int, temp: float) -> str:
        if self._cancel_flag.is_set():
            self._stage_signals.skipped.emit(stage); return ""
        self._stage_signals.running.emit(stage)
        try:
            result = self._query_model(model, prompt, ctx, temp)
            if self._cancel_flag.is_set():
                self._stage_signals.skipped.emit(stage); return ""
            self._stage_signals.done.emit(stage, result)
            return result
        except Exception as e:
            self._stage_signals.error.emit(stage, str(e)); return ""

    def _run_stage_snapshot(self, stage: StageCard, diffs: list[StageCard]) -> str:
        self._stage_signals.running.emit(stage)
        files = set()
        for d in diffs:
            files.update(_parse_file_list(d.output_text))
        root = self._project_cfg.get("root", PROJECT_ROOT)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_dir = os.path.join(SNAPSHOT_DIR, ts)
        results = []
        for f in sorted(files):
            abs_path = os.path.join(root, f) if not os.path.isabs(f) else f
            if os.path.exists(abs_path):
                dest = os.path.join(snap_dir, os.path.relpath(abs_path, root).lstrip("\\/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    shutil.copy2(abs_path, dest)
                    results.append(f"OK: {f}")
                except Exception as e:
                    results.append(f"FAIL: {f} - {e}")
            else:
                results.append(f"SKIP: {f} (new file)")
        result = "\n".join(results)
        if not results:
            result = "No files identified for snapshot."
        self._stage_signals.detail.emit(stage, result)
        self._stage_signals.done.emit(stage, f"Snapshot saved to {snap_dir}\n{result}")
        return result

    def _run_stage_apply(self, stage: StageCard, diffs: list[StageCard]) -> str:
        self._stage_signals.running.emit(stage)
        root = self._project_cfg.get("root", PROJECT_ROOT)

        combined = ""
        for d in diffs:
            combined += _extract_diffs(d.output_text) + "\n"

        if not combined.strip():
            msg = "No diffs found to apply."
            self._stage_signals.detail.emit(stage, msg)
            self._stage_signals.error.emit(stage, msg)
            return ""

        # Try git apply first, then patch
        git_result = _run_cmd(["git", "apply", "--check", "-"], cwd=root)
        if git_result[0] == 0:
            r = _run_cmd(["git", "apply", "-"], cwd=root, input_text=combined)
            if r[0] == 0:
                msg = f"Applied via git apply.\nstdout: {r[1][:200]}"
                self._stage_signals.detail.emit(stage, r[1][:500] or r[2][:500])
                self._stage_signals.done.emit(stage, msg)
                return msg
            msg = f"git apply failed (exit {r[0]}): {r[2][:500]}"
            self._stage_signals.detail.emit(stage, msg)
            self._stage_signals.error.emit(stage, msg)
            return ""

        # Fallback: write to temp patch file and use patch.exe
        patch_file = os.path.join(CONFIG_DIR, "_last_diff.patch")
        try:
            with open(patch_file, "w") as f:
                f.write(combined)
            rc, out, err = _run_cmd(["patch", "-p0", "-i", patch_file], cwd=root)
            if rc == 0:
                msg = f"Applied via patch.\n{out[:500]}"
                self._stage_signals.detail.emit(stage, out[:500])
                self._stage_signals.done.emit(stage, msg)
                return msg
            msg = f"patch failed (exit {rc}): {err[:500]}"
            self._stage_signals.detail.emit(stage, msg)
            self._stage_signals.error.emit(stage, msg)
            return ""
        except Exception as e:
            msg = f"Apply failed: {e}"
            self._stage_signals.detail.emit(stage, msg)
            self._stage_signals.error.emit(stage, msg)
            return ""

    def _run_stage_verify(self, stage: StageCard) -> str:
        self._stage_signals.running.emit(stage)
        root = self._project_cfg.get("root", PROJECT_ROOT)
        cmd_str = self._project_cfg.get("verify_cmd", "python -m compileall . 2>&1")
        try:
            rc, out, err = _run_cmd(["cmd.exe", "/c", cmd_str], cwd=root, timeout=120)
            detail = f"exit={rc}\nstdout:\n{out[:1000]}"
            if err:
                detail += f"\nstderr:\n{err[:500]}"
            self._stage_signals.detail.emit(stage, detail)
            if rc == 0:
                self._stage_signals.done.emit(stage, f"Verify PASSED (exit {rc})")
            else:
                self._stage_signals.done.emit(stage, f"Verify FAILED (exit {rc})")
            return f"exit={rc}\n{out[:500]}"
        except Exception as e:
            self._stage_signals.error.emit(stage, str(e))
            return ""

    def _run_stage_auto_commit(self, stage: StageCard) -> str:
        self._stage_signals.running.emit(stage)
        root = self._project_cfg.get("root", PROJECT_ROOT)
        rc1, out1, err1 = _run_cmd(["git", "add", "-A"], cwd=root)
        rc2, out2, err2 = _run_cmd(["git", "commit", "-m", "fauxnix-coder: auto-build"], cwd=root)
        result = f"git add: exit={rc1}\ngit commit: exit={rc2}\n{out2[:300]}"
        if rc2 == 0:
            self._stage_signals.detail.emit(stage, result)
            self._stage_signals.done.emit(stage, f"Committed: {out2.strip()[:80]}")
        else:
            self._stage_signals.detail.emit(stage, f"{result}\n{err2[:200]}")
            self._stage_signals.done.emit(stage, "Nothing to commit or git error")
        return result

    def _run_stage(self, stage: StageCard, context: str, stage_configs: list) -> str:
        cfg = stage.get_config()
        if self._cancel_flag.is_set():
            self._stage_signals.skipped.emit(stage); return ""

        if stage.kind == "model":
            prompt = stage.prompt_tpl.replace("{input}", context)
            return self._run_stage_model(stage, prompt, cfg["model"], cfg["num_ctx"], cfg["temperature"])
        elif stage.kind == "action":
            if stage.stage_id == "snapshot":
                diffs = [s for s, _ in stage_configs if s.stage_id == "diff_generator"]
                return self._run_stage_snapshot(stage, diffs)
            elif stage.stage_id == "apply":
                diffs = [s for s, _ in stage_configs if s.stage_id == "diff_generator"]
                return self._run_stage_apply(stage, diffs)
        elif stage.kind == "verify":
            return self._run_stage_verify(stage)
        return ""

    def _run_pipeline(self):
        task = self._task_input.toPlainText().strip()
        if not task:
            return

        self._save_config()
        self._running = True
        self._cancel_flag.clear()
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._task_input.setReadOnly(True)
        self._config_btn.setEnabled(False)

        stage_configs = [(s, s.get_config()) for s in self._stages]

        for stage, _ in stage_configs:
            stage.clear()
            stage.set_config_mode(False)
        self._kb_editor.hide()
        self._project_editor.hide()

        self._pipeline_status.setText(f"Building ({len(stage_configs)} stages)...")
        kb_text = read_kb_files(self._kb_paths)

        def pipeline_thread():
            context = task
            if kb_text:
                context = f"Reference files:\n{kb_text}\n\nTask:\n{task}"

            for stage, _ in stage_configs:
                if self._cancel_flag.is_set():
                    self._stage_signals.skipped.emit(stage)
                    continue
                result = self._run_stage(stage, context, stage_configs)
                if result:
                    context = f"Previous ({stage.stage_id}):\n{result}\n\nFull task:\n{task}"

            # Auto-commit if enabled and apply succeeded
            if self._project_cfg.get("auto_commit") and not self._cancel_flag.is_set():
                apply_stage = next((s for s, _ in stage_configs if s.stage_id == "apply"), None)
                if apply_stage and "done" in apply_stage._status.text() and "Applied" in apply_stage.output_text[:20]:
                    commit_stage = next((s for s, _ in stage_configs if s.stage_id == "finalizer"), None)
                    if commit_stage:
                        self._run_stage_auto_commit(commit_stage)

            self._running = False
            self._cancel_flag.clear()
            QTimer.singleShot(0, self._pipeline_done)

        threading.Thread(target=pipeline_thread, daemon=True).start()

    def _pipeline_done(self):
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._task_input.setReadOnly(False)
        self._config_btn.setEnabled(True)
        done_stages = [s for s in self._stages if "done" in s._status.text()]
        err_stages = [s for s in self._stages if "error" in s._status.text()]
        parts = [f"{len(done_stages)}/{len(self._stages)} stages complete"]
        if err_stages:
            parts.append(f"{len(err_stages)} error(s)")
        self._pipeline_status.setText(" | ".join(parts))
        self._pipeline_status.setStyleSheet(
            "color: #ff4444; font-size: 10px; font-weight: bold;" if err_stages
            else "color: #00cc66; font-size: 10px; font-weight: bold;"
        )

    def _cancel_pipeline(self):
        self._cancel_flag.set()
        for stage in self._stages:
            if "done" not in stage._status.text() and "error" not in stage._status.text():
                stage.set_skipped()
        self._pipeline_done()
