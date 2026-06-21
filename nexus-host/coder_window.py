"""Nexus Coder — multi-model coding pipeline for Fauxnix Nexus Host.

Chains models in stages: plan -> scrutinize -> diff -> test -> verify -> finalize.
Each stage uses a different model. The model per stage is configurable.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFrame, QScrollArea, QCheckBox, QComboBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from ollama_client import OLLAMA_URL

CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Fauxnix")
CONFIG_FILE = os.path.join(CONFIG_DIR, "coder-stages.json")

DEFAULT_STAGES = [
    {
        "id": "planner",
        "label": "1. Plan",
        "model": "qwen3.5:0.8b",
        "color": "#6b5b95",
        "prompt_tpl": "You are a software architect. Plan the approach for this coding task. Break it into clear steps, identify what files need changing, and outline the implementation strategy.\n\nTask:\n{input}",
    },
    {
        "id": "scrutinizer",
        "label": "2. Scrutinize",
        "model": "huihui_ai/huihui-moe-abliterated:1.5b",
        "color": "#d64161",
        "prompt_tpl": "You are a senior code reviewer. Scrutinize the following plan. Identify gaps, risks, edge cases, missing error handling, performance concerns, and architectural issues.\n\nPlan:\n{input}",
    },
    {
        "id": "diff_generator",
        "label": "3. Generate Diffs",
        "model": "granite-code:20b",
        "color": "#00b4d8",
        "prompt_tpl": "You are a senior developer. Based on the plan and review below, generate the actual code diffs. Use unified diff format (---/+++). Be precise about file paths, line numbers, and changes.\n\nInput:\n{input}",
    },
    {
        "id": "tester",
        "label": "4. Write Tests",
        "model": "minicpm-v4.6:latest",
        "color": "#90be6d",
        "prompt_tpl": "You are a testing specialist. Write tests for the code changes described below. Include unit tests, edge cases, and any integration test considerations.\n\nCode changes:\n{input}",
    },
    {
        "id": "verifier",
        "label": "5. Verify",
        "model": "minicpm-v4.6:latest",
        "color": "#f9c74f",
        "prompt_tpl": "You are a QA engineer. Verify the code changes and tests below. Check for correctness, completeness, edge case coverage, and potential regressions.\n\nChanges and tests:\n{input}",
    },
    {
        "id": "finalizer",
        "label": "6. Final Review",
        "model": "qwen3.5:0.8b",
        "color": "#43aa8b",
        "prompt_tpl": "You are a project lead. Review the entire pipeline output below: plan, scrutiny, diffs, tests, verification. Determine if the task is complete and safe to apply. Give a CLEAR PASS/FAIL/NEEDS_REVISION verdict.\n\nFull output:\n{input}",
    },
]


def load_stages() -> list[dict]:
    try:
        with open(CONFIG_FILE, "r") as f:
            saved = json.load(f)
        if isinstance(saved, list) and len(saved) == len(DEFAULT_STAGES):
            return saved
    except Exception:
        pass
    return [dict(s) for s in DEFAULT_STAGES]


def save_stages(stages: list[dict]):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(stages, f, indent=2)


def _fetch_models() -> list[str]:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


class StageCard(QFrame):
    """A single pipeline stage with status, output, and model config."""

    def __init__(self, stage_def: dict, models: list[str], parent=None):
        super().__init__(parent)
        self.stage_id = stage_def["id"]
        self.color = stage_def["color"]
        self.prompt_tpl = stage_def["prompt_tpl"]
        self.output_text = ""
        self._config_mode = False
        self._build_ui(stage_def, models)

    def _build_ui(self, stage_def: dict, models: list[str]):
        self.setStyleSheet(
            "StageCard { background: #141518; border: 1px solid #2a2d33; border-radius: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        self._label = QLabel(stage_def["label"])
        self._label.setStyleSheet(f"color: {self.color}; font-size: 11px; font-weight: bold;")
        header.addWidget(self._label)
        header.addStretch()

        # Model badge (visible in run mode)
        self._badge = QLabel(stage_def["model"])
        self._badge.setStyleSheet(
            f"background: {self.color}; color: #080909; font-size: 9px; "
            f"padding: 2px 6px; border-radius: 3px; font-weight: bold;"
        )
        header.addWidget(self._badge)

        # Model combo (visible in config mode)
        self._combo = QComboBox()
        self._combo.setMinimumWidth(180)
        self._combo.setStyleSheet(
            "QComboBox { background: #1c1e23; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 3px; padding: 2px 4px; font-size: 10px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #141518; color: #d4d4d4; "
            "selection-background-color: #ff7800; }"
        )
        if models:
            self._combo.addItems(models)
        idx = self._combo.findText(stage_def["model"])
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.hide()
        header.addWidget(self._combo)

        self._status = QLabel("waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        header.addWidget(self._status)
        layout.addLayout(header)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(100)
        self._output.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0b0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
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
            self._output.append(f'\n... ({len(text)} total chars)')

    def set_error(self, err: str):
        self._status.setText("error")
        self._status.setStyleSheet("color: #ff4444; font-size: 10px; font-weight: bold;")
        self._output.clear()
        self._output.append(f'{err}')

    def set_skipped(self):
        self._status.setText("skipped")
        self._status.setStyleSheet("color: #666; font-size: 10px;")

    def clear(self):
        self.output_text = ""
        self._status.setText("waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        self._output.clear()


class CoderWindow(QWidget):
    """Multi-model coding pipeline tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: list[StageCard] = []
        self._stage_defs: list[dict] = []
        self._models: list[str] = []
        self._running = False
        self._config_mode = False
        self._cancel_flag = threading.Event()
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

        self._config_btn = QPushButton("Configure Models")
        self._config_btn.setStyleSheet(
            "QPushButton { background: #1c1e23; color: #b0b0b0; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 5px 12px; font-size: 10px; }"
            "QPushButton:hover { background: #2a2d33; color: #d4d4d4; }"
            "QPushButton:checked { background: #ff7800; color: #080909; border-color: #ff7800; }"
        )
        self._config_btn.setCheckable(True)
        self._config_btn.toggled.connect(self._toggle_config)
        header.addWidget(self._config_btn)

        self._run_btn = QPushButton("Run Pipeline")
        self._run_btn.setStyleSheet(
            "QPushButton { background: #00cc66; color: #080909; border: none; "
            "border-radius: 4px; padding: 5px 14px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #00e673; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self._run_btn.clicked.connect(self._run_pipeline)
        header.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: #d64161; color: #fff; border: none; "
            "border-radius: 4px; padding: 5px 14px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #e05575; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self._cancel_btn.clicked.connect(self._cancel_pipeline)
        self._cancel_btn.setEnabled(False)
        header.addWidget(self._cancel_btn)
        layout.addLayout(header)

        # Task input
        input_label = QLabel("Coding Task:")
        input_label.setStyleSheet("color: #b0b0b0; font-size: 11px; font-weight: bold;")
        layout.addWidget(input_label)

        self._task_input = QTextEdit()
        self._task_input.setPlaceholderText("Describe the coding task...")
        self._task_input.setMaximumHeight(70)
        self._task_input.setStyleSheet(
            "QTextEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
            "QTextEdit:focus { border-color: #ff7800; }"
        )
        layout.addWidget(self._task_input)

        # Pipeline stages
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 6px; background: #0d0e12; }"
            "QScrollBar::handle:vertical { background: #2a2d33; border-radius: 3px; }"
        )

        self._stages_widget = QWidget()
        self._stages_widget.setStyleSheet("background: transparent;")
        self._stages_layout = QVBoxLayout(self._stages_widget)
        self._stages_layout.setContentsMargins(0, 0, 0, 0)
        self._stages_layout.setSpacing(4)

        self._stage_defs = load_stages()
        self._rebuild_stages()
        self._scroll.setWidget(self._stages_widget)
        layout.addWidget(self._scroll, 1)

        self._fetch_models_async()

    def _fetch_models_async(self):
        def fetch():
            self._models = _fetch_models()
            QTimer.singleShot(0, self._refresh_combos)

        t = threading.Thread(target=fetch, daemon=True)
        t.start()

    def _refresh_combos(self):
        for card in self._stages:
            current = card._badge.text()
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
        self._config_btn.setText("Done Configuring" if checked else "Configure Models")
        self._run_btn.setEnabled(not checked)

        if checked:
            self._fetch_models_async()

        for card in self._stages:
            card.set_config_mode(checked)

        if not checked:
            self._save_config()

    def _save_config(self):
        for i, card in enumerate(self._stages):
            if i < len(self._stage_defs):
                self._stage_defs[i]["model"] = card.model
        save_stages(self._stage_defs)

    def _query_model(self, model: str, prompt: str, timeout: int = 120) -> str:
        body = json.dumps({
            "model": model, "prompt": prompt,
            "stream": False, "options": {"num_predict": 2048, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()

    def _run_stage(self, stage: StageCard, prompt: str) -> str:
        if self._cancel_flag.is_set():
            stage.set_skipped()
            return ""
        stage.set_running()
        QTimer.singleShot(50, lambda: None)
        try:
            result = self._query_model(stage.model, prompt)
            if self._cancel_flag.is_set():
                stage.set_skipped()
                return ""
            stage.set_done(result)
            return result
        except Exception as e:
            stage.set_error(str(e))
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

        for stage in self._stages:
            stage.clear()
            stage.set_config_mode(False)
        self._config_btn.setEnabled(False)

        def pipeline_thread():
            context = task
            for stage in self._stages:
                if self._cancel_flag.is_set():
                    break
                prompt = stage.prompt_tpl.replace("{input}", context)
                result = self._run_stage(stage, prompt)
                if result:
                    context = f"Previous stage output ({stage.stage_id}):\n{result}\n\nFull task:\n{task}"

            self._running = False
            self._cancel_flag.clear()
            QTimer.singleShot(0, self._pipeline_done)

        t = threading.Thread(target=pipeline_thread, daemon=True)
        t.start()

    def _pipeline_done(self):
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._task_input.setReadOnly(False)
        self._config_btn.setEnabled(True)

    def _cancel_pipeline(self):
        self._cancel_flag.set()
        for stage in self._stages:
            if "done" not in stage._status.text() and "error" not in stage._status.text():
                stage.set_skipped()
        self._pipeline_done()

    def stage_output(self, stage_id: str) -> str:
        for stage in self._stages:
            if stage.stage_id == stage_id:
                return stage.output_text
        return ""
