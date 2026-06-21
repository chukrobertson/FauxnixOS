"""Nexus Coder — multi-model coding pipeline with knowledge base support."""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFrame, QScrollArea, QCheckBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

from ollama_client import OLLAMA_URL

CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Fauxnix")
CONFIG_FILE = os.path.join(CONFIG_DIR, "coder-config.json")

DEFAULT_STAGES = [
    {"id": "planner", "label": "1. Plan", "model": "qwen3.5:0.8b", "color": "#6b5b95", "num_ctx": 8192, "temperature": 0.7, "use_kb": True, "prompt_tpl": "You are a software architect. Plan the approach for this coding task.\n\nTask:\n{input}"},
    {"id": "scrutinizer", "label": "2. Scrutinize", "model": "huihui_ai/huihui-moe-abliterated:1.5b", "color": "#d64161", "num_ctx": 8192, "temperature": 0.3, "use_kb": True, "prompt_tpl": "You are a senior code reviewer. Scrutinize the plan below. Identify gaps, risks, edge cases.\n\nPlan:\n{input}"},
    {"id": "diff_generator", "label": "3. Generate Diffs", "model": "granite-code:20b", "color": "#00b4d8", "num_ctx": 16384, "temperature": 0.2, "use_kb": True, "prompt_tpl": "You are a senior developer. Generate the actual code diffs in unified format.\n\nInput:\n{input}"},
    {"id": "tester", "label": "4. Write Tests", "model": "minicpm-v4.6:latest", "color": "#90be6d", "num_ctx": 8192, "temperature": 0.4, "use_kb": False, "prompt_tpl": "You are a testing specialist. Write tests for the code changes below.\n\nCode changes:\n{input}"},
    {"id": "verifier", "label": "5. Verify", "model": "minicpm-v4.6:latest", "color": "#f9c74f", "num_ctx": 8192, "temperature": 0.3, "use_kb": True, "prompt_tpl": "You are a QA engineer. Verify the code changes and tests below.\n\nChanges and tests:\n{input}"},
    {"id": "finalizer", "label": "6. Final Review", "model": "qwen3.5:0.8b", "color": "#43aa8b", "num_ctx": 8192, "temperature": 0.5, "use_kb": True, "prompt_tpl": "You are a project lead. Review the full pipeline output below. Give a CLEAR PASS/FAIL/NEEDS_REVISION verdict.\n\nFull output:\n{input}"},
]


def load_config() -> tuple[list[dict], list[str]]:
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and "stages" in data:
            stages = data["stages"]
            kb = data.get("knowledge_base", [])
            if isinstance(stages, list) and len(stages) == len(DEFAULT_STAGES):
                return stages, kb
        if isinstance(data, list) and len(data) == len(DEFAULT_STAGES):
            return data, []
    except Exception:
        pass
    return [dict(s) for s in DEFAULT_STAGES], []


def save_config(stages: list[dict], kb: list[str]):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"stages": stages, "knowledge_base": kb}, f, indent=2)


def read_kb_files(paths: list[str]) -> str:
    parts = []
    for p in paths:
        p = p.strip()
        if not p:
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            parts.append(f"--- {p} ---\n{content}")
        except Exception as e:
            parts.append(f"--- {p} ---\n(unreadable: {e})")
    if parts:
        return "\n\n".join(parts)
    return ""


def _fetch_models() -> list[str]:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


class StageCard(QFrame):
    def __init__(self, stage_def: dict, models: list[str], parent=None):
        super().__init__(parent)
        self.stage_id = stage_def["id"]
        self.color = stage_def["color"]
        self.prompt_tpl = stage_def["prompt_tpl"]
        self.output_text = ""
        self._config_mode = False
        self._build_ui(stage_def, models)

    def _build_ui(self, sd: dict, models: list[str]):
        self.setStyleSheet("StageCard { background: #141518; border: 1px solid #2a2d33; border-radius: 6px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        # Header row: label + model badge/combo + status
        header = QHBoxLayout()
        self._label = QLabel(sd["label"])
        self._label.setStyleSheet(f"color: {self.color}; font-size: 11px; font-weight: bold;")
        header.addWidget(self._label)
        header.addStretch()

        self._badge = QLabel(sd["model"])
        self._badge.setStyleSheet(f"background: {self.color}; color: #080909; font-size: 9px; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
        header.addWidget(self._badge)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(160)
        self._combo.setStyleSheet("QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 4px; font-size: 10px; } QComboBox::drop-down { border: none; } QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; selection-background-color: #ff7800; }")
        if models:
            self._combo.addItems(models)
        idx = self._combo.findText(sd["model"])
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.currentTextChanged.connect(self._badge.setText)
        self._combo.hide()
        header.addWidget(self._combo)

        self._status = QLabel("waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        header.addWidget(self._status)
        layout.addLayout(header)

        # Config row (hidden in run mode): KB checkbox + ctx + temp
        self._config_row = QHBoxLayout()

        self._use_kb_cb = QCheckBox("Use KB")
        self._use_kb_cb.setChecked(sd.get("use_kb", True))
        self._use_kb_cb.setStyleSheet("QCheckBox { color: #888; font-size: 9px; spacing: 3px; }")
        self._config_row.addWidget(self._use_kb_cb)

        ctx_label = QLabel("Ctx:")
        ctx_label.setStyleSheet("color: #666; font-size: 9px;")
        self._config_row.addWidget(ctx_label)
        self._ctx_spin = QSpinBox()
        self._ctx_spin.setRange(2048, 65536)
        self._ctx_spin.setSingleStep(2048)
        self._ctx_spin.setValue(sd.get("num_ctx", 8192))
        self._ctx_spin.setStyleSheet("QSpinBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 2px; padding: 1px 3px; font-size: 9px; max-width: 70px; }")
        self._config_row.addWidget(self._ctx_spin)

        temp_label = QLabel("Temp:")
        temp_label.setStyleSheet("color: #666; font-size: 9px;")
        self._config_row.addWidget(temp_label)
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0)
        self._temp_spin.setSingleStep(0.1)
        self._temp_spin.setValue(sd.get("temperature", 0.7))
        self._temp_spin.setStyleSheet("QDoubleSpinBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 2px; padding: 1px 3px; font-size: 9px; max-width: 60px; }")
        self._config_row.addWidget(self._temp_spin)

        self._config_row.addStretch()
        self._config_row_widget = QWidget()
        self._config_row_widget.setLayout(self._config_row)
        self._config_row_widget.setStyleSheet("background: transparent;")
        self._config_row_widget.hide()
        layout.addWidget(self._config_row_widget)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(90)
        self._output.setStyleSheet("QTextEdit { background: #0d0e12; color: #b0b0b0; border: 1px solid #1e1e24; border-radius: 4px; padding: 4px; font-size: 10px; }")
        layout.addWidget(self._output)

    @property
    def model(self) -> str:
        if self._combo.isVisible():
            return self._combo.currentText()
        return self._badge.text()

    @model.setter
    def model(self, value: str):
        self._badge.setText(value)
        idx = self._combo.findText(value)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

    def set_config_mode(self, enabled: bool):
        self._config_mode = enabled
        self._badge.setVisible(not enabled)
        self._combo.setVisible(enabled)
        self._config_row_widget.setVisible(enabled)

    def get_config(self) -> dict:
        return {
            "model": self._combo.currentText() if self._combo.isVisible() else self._badge.text(),
            "use_kb": self._use_kb_cb.isChecked(),
            "num_ctx": self._ctx_spin.value(),
            "temperature": self._temp_spin.value(),
        }

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


class StageSignals(QObject):
    running = pyqtSignal(object)
    done = pyqtSignal(object, str)
    error = pyqtSignal(object, str)
    skipped = pyqtSignal(object)


class CoderWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: list[StageCard] = []
        self._stage_defs: list[dict] = []
        self._kb_paths: list[str] = []
        self._models: list[str] = []
        self._running = False
        self._config_mode = False
        self._cancel_flag = threading.Event()
        self._stage_signals = StageSignals()
        self._stage_signals.running.connect(self._on_stage_running)
        self._stage_signals.done.connect(self._on_stage_done)
        self._stage_signals.error.connect(self._on_stage_error)
        self._stage_signals.skipped.connect(self._on_stage_skipped)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("background: #0d0e12;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
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

        self._run_btn = QPushButton("Run")
        self._run_btn.setStyleSheet("QPushButton { background: #00cc66; color: #080909; border: none; border-radius: 4px; padding: 5px 14px; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #00e673; } QPushButton:disabled { background: #333; color: #666; }")
        self._run_btn.clicked.connect(self._run_pipeline)
        header.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet("QPushButton { background: #d64161; color: #fff; border: none; border-radius: 4px; padding: 5px 14px; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #e05575; } QPushButton:disabled { background: #333; color: #666; }")
        self._cancel_btn.clicked.connect(self._cancel_pipeline)
        self._cancel_btn.setEnabled(False)
        header.addWidget(self._cancel_btn)
        layout.addLayout(header)

        # Task input
        layout.addWidget(QLabel("Coding Task:"))
        self._task_input = QTextEdit()
        self._task_input.setPlaceholderText("Describe the coding task...")
        self._task_input.setMaximumHeight(70)
        self._task_input.setStyleSheet("QTextEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; border-radius: 6px; padding: 8px; font-size: 12px; } QTextEdit:focus { border-color: #ff7800; }")
        layout.addWidget(self._task_input)

        # Pipeline status
        self._pipeline_status = QLabel("")
        self._pipeline_status.setStyleSheet("color: #888; font-size: 10px; font-weight: bold;")
        layout.addWidget(self._pipeline_status)

        # KB status
        self._kb_label = QLabel("")
        self._kb_label.setStyleSheet("color: #666; font-size: 9px;")
        layout.addWidget(self._kb_label)

        # Pipeline scroll
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollBar:vertical { width: 6px; background: #0d0e12; } QScrollBar::handle:vertical { background: #2a2d33; border-radius: 3px; }")
        self._stages_widget = QWidget()
        self._stages_widget.setStyleSheet("background: transparent;")
        self._stages_layout = QVBoxLayout(self._stages_widget)
        self._stages_layout.setContentsMargins(0, 0, 0, 0)
        self._stages_layout.setSpacing(4)

        self._stage_defs, self._kb_paths = load_config()
        self._rebuild_stages()
        self._update_kb_label()
        self._scroll.setWidget(self._stages_widget)
        layout.addWidget(self._scroll, 1)

        # KB Editor (visible in config mode)
        self._kb_editor = QWidget()
        self._kb_editor.setStyleSheet("background: transparent;")
        kb_edit_layout = QVBoxLayout(self._kb_editor)
        kb_edit_layout.setContentsMargins(0, 0, 0, 0)
        kb_edit_layout.setSpacing(4)

        kb_header = QHBoxLayout()
        kb_title = QLabel("Knowledge Base Files:")
        kb_title.setStyleSheet("color: #b0b0b0; font-size: 10px; font-weight: bold;")
        kb_header.addWidget(kb_title)
        kb_header.addStretch()

        self._add_file_btn = QPushButton("+ Add File")
        self._add_file_btn.setStyleSheet("QPushButton { background: #1c1e23; color: #00c8ff; border: 1px solid #00c8ff; border-radius: 3px; padding: 2px 8px; font-size: 9px; } QPushButton:hover { background: #00c8ff; color: #080909; }")
        self._add_file_btn.clicked.connect(self._add_kb_file)
        kb_header.addWidget(self._add_file_btn)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.setStyleSheet("QPushButton { background: #1c1e23; color: #b0b0b0; border: 1px solid #2a2d33; border-radius: 3px; padding: 2px 8px; font-size: 9px; } QPushButton:hover { background: #2a2d33; }")
        self._browse_btn.clicked.connect(self._browse_kb_file)
        kb_header.addWidget(self._browse_btn)

        kb_edit_layout.addLayout(kb_header)

        self._kb_list = QListWidget()
        self._kb_list.setStyleSheet("QListWidget { background: #0d0e12; color: #b0b0b0; border: 1px solid #2a2d33; border-radius: 4px; font-size: 9px; } QListWidget::item { padding: 2px 4px; }")
        self._kb_list.setMaximumHeight(120)
        kb_edit_layout.addWidget(self._kb_list)

        remove_row = QHBoxLayout()
        self._remove_sel_btn = QPushButton("Remove Selected")
        self._remove_sel_btn.setStyleSheet("QPushButton { background: #d64161; color: #fff; border: none; border-radius: 3px; padding: 2px 8px; font-size: 9px; } QPushButton:hover { background: #e05575; }")
        self._remove_sel_btn.clicked.connect(self._remove_kb_file)
        remove_row.addWidget(self._remove_sel_btn)
        remove_row.addStretch()
        kb_edit_layout.addLayout(remove_row)

        self._kb_editor.hide()
        layout.addWidget(self._kb_editor)

        self._fetch_models_async()

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

    def _on_stage_running(self, stage: StageCard):
        stage.set_running()
        self._pipeline_status.setText(f"Running: {stage._label.text()} ({stage.model})")
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

    def _on_stage_skipped(self, stage: StageCard):
        stage.set_skipped()

    def _fetch_models_async(self):
        def fetch():
            self._models = _fetch_models()
            QTimer.singleShot(0, self._refresh_combos)
        threading.Thread(target=fetch, daemon=True).start()

    def _refresh_combos(self):
        for card in self._stages:
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

        if checked:
            self._fetch_models_async()
            self._populate_kb_list()

        for card in self._stages:
            card.set_config_mode(checked)

        if not checked:
            self._save_config()

    def _save_config(self):
        for i, card in enumerate(self._stages):
            if i < len(self._stage_defs):
                self._stage_defs[i].update(card.get_config())
        save_config(self._stage_defs, self._kb_paths)

    def _query_model(self, model: str, prompt: str, ctx: int, temp: float, timeout: int = 180) -> str:
        body = json.dumps({
            "model": model, "prompt": prompt, "stream": False,
            "options": {"num_predict": 4096, "num_ctx": ctx, "temperature": temp},
        }).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()

    def _run_stage(self, stage: StageCard, prompt: str, model: str, ctx: int, temp: float) -> str:
        if self._cancel_flag.is_set():
            self._stage_signals.skipped.emit(stage)
            return ""
        self._stage_signals.running.emit(stage)
        try:
            result = self._query_model(model, prompt, ctx, temp)
            if self._cancel_flag.is_set():
                self._stage_signals.skipped.emit(stage)
                return ""
            self._stage_signals.done.emit(stage, result)
            return result
        except Exception as e:
            self._stage_signals.error.emit(stage, str(e))
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

        # Capture all stage configs upfront (main thread)
        stage_configs = [(s, s.get_config()) for s in self._stages]

        for stage, _ in stage_configs:
            stage.clear()
            stage.set_config_mode(False)
        self._kb_editor.hide()

        self._pipeline_status.setText(f"Starting pipeline ({len(stage_configs)} stages)...")
        self._pipeline_status.setStyleSheet("color: #888; font-size: 10px; font-weight: bold;")

        kb_text = read_kb_files(self._kb_paths)

        def pipeline_thread():
            context = task
            if kb_text:
                context = f"Reference files:\n{kb_text}\n\nTask:\n{task}"

            for stage, cfg in stage_configs:
                if self._cancel_flag.is_set():
                    self._stage_signals.skipped.emit(stage)
                    continue
                prompt = stage.prompt_tpl.replace("{input}", context if cfg["use_kb"] else task)
                result = self._run_stage(stage, prompt, cfg["model"], cfg["num_ctx"], cfg["temperature"])
                if result:
                    context = f"Previous ({stage.stage_id}):\n{result}\n\nFull task:\n{task}"

            self._running = False
            self._cancel_flag.clear()
            QTimer.singleShot(0, self._pipeline_done)

        threading.Thread(target=pipeline_thread, daemon=True).start()

    def _pipeline_done(self):
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._task_input.setReadOnly(False)
        self._config_btn.setEnabled(True)

        # Show summary in status
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
