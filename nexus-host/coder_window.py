"""Nexus Coder — multi-model coding pipeline for Fauxnix Nexus Host.

Chains models in stages: plan → scrutinize → diff → test → verify → finalize.
Each stage uses a different model appropriate to the task.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFrame, QScrollArea, QCheckBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor

from ollama_client import OLLAMA_URL

STAGES = [
    {
        "id": "planner",
        "label": "1. Plan",
        "model": "qwen3.5:0.8b",
        "color": "#6b5b95",
        "prompt_tpl": "You are a software architect. Plan the approach for this coding task. Break it into clear steps, identify what files need changing, and outline the implementation strategy.\n\nTask:\n{input}",
        "instructions": "Plans the approach using qwen3.5:0.8b (fast admin model)",
    },
    {
        "id": "scrutinizer",
        "label": "2. Scrutinize",
        "model": "huihui_ai/huihui-moe-abliterated:1.5b",
        "color": "#d64161",
        "prompt_tpl": "You are a senior code reviewer. Scrutinize the following plan. Identify gaps, risks, edge cases, missing error handling, performance concerns, and architectural issues. Be thorough and constructive.\n\nPlan:\n{input}",
        "instructions": "Reviews the plan using moe-abliterated:1.5b (reasoning model)",
    },
    {
        "id": "diff_generator",
        "label": "3. Generate Diffs",
        "model": "granite-code:20b",
        "color": "#00b4d8",
        "prompt_tpl": "You are a senior developer. Based on the plan and review below, generate the actual code diffs. Use unified diff format (---/+++). Be precise about file paths, line numbers, and changes.\n\nPlan:\n{input}",
        "instructions": "Generates code diffs using granite-code:20b (code specialist)",
    },
    {
        "id": "tester",
        "label": "4. Write Tests",
        "model": "minicpm-v4.6:latest",
        "color": "#90be6d",
        "prompt_tpl": "You are a testing specialist. Write tests for the code changes described below. Include unit tests, edge cases, and any integration test considerations.\n\nCode changes:\n{input}",
        "instructions": "Writes tests using minicpm-v4.6:latest (fast coder)",
    },
    {
        "id": "verifier",
        "label": "5. Verify",
        "model": "minicpm-v4.6:latest",
        "color": "#f9c74f",
        "prompt_tpl": "You are a QA engineer. Verify the code changes and tests below. Check for correctness, completeness, edge case coverage, and potential regressions. Report pass/fail for each check.\n\nChanges and tests:\n{input}",
        "instructions": "Verifies correctness using minicpm-v4.6:latest",
    },
    {
        "id": "finalizer",
        "label": "6. Final Review",
        "model": "qwen3.5:0.8b",
        "color": "#43aa8b",
        "prompt_tpl": "You are a project lead. Review the entire pipeline output below: plan, scrutiny, diffs, tests, verification. Determine if the task is complete and safe to apply. Give a final summary and a CLEAR PASS/FAIL/NEEDS_REVISION verdict.\n\nFull pipeline output:\n{input}",
        "instructions": "Final review using qwen3.5:0.8b (admin model)",
    },
]


class StageCard(QFrame):
    """A single pipeline stage with status and output."""

    def __init__(self, stage_def: dict, parent=None):
        super().__init__(parent)
        self.stage_id = stage_def["id"]
        self.model = stage_def["model"]
        self.color = stage_def["color"]
        self.prompt_tpl = stage_def["prompt_tpl"]
        self.instructions = stage_def["instructions"]
        self.output_text = ""
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            "StageCard { background: #141518; border: 1px solid #2a2d33; border-radius: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header row: label + model badge + status
        header = QHBoxLayout()
        self._label = QLabel(f'<span style="color:{self.color}; font-weight:bold;">{self.instructions}</span>')
        self._label.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(self._label)
        header.addStretch()

        self._badge = QLabel(self.model)
        self._badge.setStyleSheet(
            f"background: {self.color}; color: #080909; font-size: 9px; "
            f"padding: 2px 6px; border-radius: 3px; font-weight: bold;"
        )
        header.addWidget(self._badge)

        self._status = QLabel("⏳ waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        header.addWidget(self._status)
        layout.addLayout(header)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(120)
        self._output.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0b0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._output)

    def set_running(self):
        self._status.setText("▶ running")
        self._status.setStyleSheet("color: #00c8ff; font-size: 10px; font-weight: bold;")
        self._output.clear()
        self._output.append('<span style="color:#888;">Running...</span>')

    def set_done(self, text: str):
        self.output_text = text
        self._status.setText("✓ done")
        self._status.setStyleSheet("color: #00cc66; font-size: 10px; font-weight: bold;")
        self._output.clear()
        self._output.append(text[:500])
        if len(text) > 500:
            self._output.append(f'\n<span style="color:#666;">... ({len(text)} total chars)</span>')

    def set_error(self, err: str):
        self._status.setText("✗ error")
        self._status.setStyleSheet("color: #ff4444; font-size: 10px; font-weight: bold;")
        self._output.clear()
        self._output.append(f'<span style="color:#ff4444;">{err}</span>')

    def set_skipped(self):
        self._status.setText("— skipped")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        self._output.clear()
        self._output.append('<span style="color:#666;">Stage skipped.</span>')

    def clear(self):
        self.output_text = ""
        self._status.setText("⏳ waiting")
        self._status.setStyleSheet("color: #666; font-size: 10px;")
        self._output.clear()


class CoderWindow(QWidget):
    """Multi-model coding pipeline tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: list[StageCard] = []
        self._running = False
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

        self._run_btn = QPushButton("▶ Run Pipeline")
        self._run_btn.setStyleSheet(
            "QPushButton { background: #00cc66; color: #080909; border: none; "
            "border-radius: 4px; padding: 6px 14px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #00e673; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self._run_btn.clicked.connect(self._run_pipeline)
        header.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: #d64161; color: #fff; border: none; "
            "border-radius: 4px; padding: 6px 14px; font-size: 11px; font-weight: bold; }"
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
        self._task_input.setPlaceholderText(
            "Describe the coding task... e.g., 'Add a retry decorator to the HTTP client with exponential backoff'"
        )
        self._task_input.setMaximumHeight(80)
        self._task_input.setStyleSheet(
            "QTextEdit { background: #141518; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
            "QTextEdit:focus { border-color: #ff7800; }"
        )
        layout.addWidget(self._task_input)

        # Auto-run toggle
        auto_row = QHBoxLayout()
        self._auto_scroll = QCheckBox("Auto-scroll to latest stage")
        self._auto_scroll.setChecked(True)
        self._auto_scroll.setStyleSheet("color: #888; font-size: 10px;")
        auto_row.addWidget(self._auto_scroll)
        auto_row.addStretch()
        layout.addLayout(auto_row)

        # Pipeline stages in scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 6px; background: #0d0e12; }"
            "QScrollBar::handle:vertical { background: #2a2d33; border-radius: 3px; }"
        )

        stages_widget = QWidget()
        stages_widget.setStyleSheet("background: transparent;")
        self._stages_layout = QVBoxLayout(stages_widget)
        self._stages_layout.setContentsMargins(0, 0, 0, 0)
        self._stages_layout.setSpacing(4)

        for sd in STAGES:
            card = StageCard(sd)
            self._stages.append(card)
            self._stages_layout.addWidget(card)

        self._stages_layout.addStretch()
        scroll.setWidget(stages_widget)
        layout.addWidget(scroll, 1)

    def _query_model(self, model: str, prompt: str, timeout: int = 120) -> str:
        """Call Ollama with a prompt and return the response."""
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 2048, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=body, method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()

    def _run_stage(self, stage: StageCard, prompt: str) -> str:
        """Run a single stage and update its UI."""
        if self._cancel_flag.is_set():
            stage.set_skipped()
            return ""
        stage.set_running()
        QTimer.singleShot(50, lambda: None)  # Process events

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

        self._running = True
        self._cancel_flag.clear()
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._task_input.setReadOnly(True)

        for stage in self._stages:
            stage.clear()

        def pipeline_thread():
            context = task
            for stage in self._stages:
                if self._cancel_flag.is_set():
                    break
                prompt = stage.prompt_tpl.replace("{input}", context)
                result = self._run_stage(stage, prompt)
                if result:
                    context = f"Previous stage output ({stage.stage_id}):\n{result}\n\nFull task:\n{task}"
                if self._auto_scroll.isChecked():
                    stage.ensureVisible()

            self._running = False
            self._cancel_flag.clear()
            QTimer.singleShot(0, self._pipeline_done)

        t = threading.Thread(target=pipeline_thread, daemon=True)
        t.start()

    def _pipeline_done(self):
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._task_input.setReadOnly(False)

    def _cancel_pipeline(self):
        self._cancel_flag.set()
        for stage in self._stages:
            if stage._status.text() not in ("✓ done", "✗ error", "— skipped"):
                stage.set_skipped()
        self._pipeline_done()

    def stage_output(self, stage_id: str) -> str:
        for stage in self._stages:
            if stage.stage_id == stage_id:
                return stage.output_text
        return ""
