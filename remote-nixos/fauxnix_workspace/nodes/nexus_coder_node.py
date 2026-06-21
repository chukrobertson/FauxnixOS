"""Nexus Coder Node — multi-model coding pipeline on the workspace canvas.

Chains models on the Nexus Windows desktop: plan → scrutinize → diff → test → verify → finalize.
Mirrors the pipeline of coder_window.py but routes through the Nexus Ollama API.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFrame, QScrollArea, QCheckBox,
)

from ..canvas import BaseNodeWidget, register_node_type, SocketItem
from ..theme import NODE_BG

NEXUS_IP = "100.126.117.60"
NEXUS_PORT = 11434

STAGES = [
    {"id": "planner", "label": "1. Plan", "model": "qwen3.5:0.8b", "color": "#6b5b95"},
    {"id": "scrutinizer", "label": "2. Scrutinize", "model": "huihui_ai/huihui-moe-abliterated:1.5b", "color": "#d64161"},
    {"id": "diff_generator", "label": "3. Generate Diffs", "model": "granite-code:20b", "color": "#00b4d8"},
    {"id": "tester", "label": "4. Write Tests", "model": "minicpm-v4.6:latest", "color": "#90be6d"},
    {"id": "verifier", "label": "5. Verify", "model": "minicpm-v4.6:latest", "color": "#f9c74f"},
    {"id": "finalizer", "label": "6. Final Review", "model": "qwen3.5:0.8b", "color": "#43aa8b"},
]


@register_node_type("Nexus Coder", "Multi-model coding pipeline: plan → scrutinize → diff → test → verify → finalize via Nexus")
class NexusCoderNode(BaseNodeWidget):
    def __init__(self):
        super().__init__("Nexus Coder", QColor("#1a1025"), 360)
        self._stage_outputs: dict[str, str] = {}
        self._stage_labels: list[QLabel] = []
        self._running = False
        self._cancel_flag = threading.Event()
        self._build_ui()
        self.add_socket("in", "text")
        self.add_socket("out", "text")

    def _build_ui(self):
        w = QWidget()
        w.setStyleSheet(f"background: {NODE_BG.name()};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        # Status header
        self._status = QLabel("Nexus Coder: idle")
        self._status.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        layout.addWidget(self._status)

        # Task input
        self._task_input = QTextEdit()
        self._task_input.setPlaceholderText("Describe the coding task...")
        self._task_input.setMaximumHeight(60)
        self._task_input.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #d4d4d4; border: 1px solid #2a2d33; "
            "border-radius: 4px; padding: 4px; font-size: 10px; }"
        )
        layout.addWidget(self._task_input)

        # Run button
        self._run_btn = QPushButton("▶ Run Pipeline")
        self._run_btn.setStyleSheet(
            "QPushButton { background: #00cc66; color: #080909; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 10px; font-weight: bold; }"
            "QPushButton:hover { background: #00e673; }"
            "QPushButton:disabled { background: #333; color: #666; }"
        )
        self._run_btn.clicked.connect(self._run_pipeline)
        layout.addWidget(self._run_btn)

        # Stages
        stages_label = QLabel("Pipeline:")
        stages_label.setStyleSheet("color: #b0b0b0; font-size: 10px; font-weight: bold;")
        layout.addWidget(stages_label)

        for sd in STAGES:
            row = QHBoxLayout()
            dot = QLabel(f"●")
            dot.setStyleSheet(f"color: {sd['color']}; font-size: 10px;")
            row.addWidget(dot)
            lbl = QLabel(f"{sd['label']}  [{sd['model']}]")
            lbl.setStyleSheet("color: #888; font-size: 9px;")
            row.addWidget(lbl)
            row.addStretch()
            status = QLabel("⏳")
            status.setStyleSheet("color: #666; font-size: 9px;")
            self._stage_labels.append(status)
            row.addWidget(status)
            layout.addLayout(row)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(100)
        self._output.setStyleSheet(
            "QTextEdit { background: #0d0e12; color: #b0b0b0; border: 1px solid #1e1e24; "
            "border-radius: 4px; padding: 4px; font-size: 9px; }"
        )
        layout.addWidget(self._output)

        w.setFixedHeight(300)
        self.set_body_widget(w)

    def _query_model(self, model: str, prompt: str) -> str:
        body = json.dumps({
            "model": model, "prompt": prompt,
            "stream": False, "options": {"num_predict": 2048, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{NEXUS_IP}:{NEXUS_PORT}/api/generate",
            data=body, method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()

    def _set_stage(self, index: int, status: str, color: str):
        if index < len(self._stage_labels):
            self._stage_labels[index].setText(status)
            self._stage_labels[index].setStyleSheet(f"color: {color}; font-size: 9px; font-weight: bold;")

    def _run_pipeline(self):
        task = self._task_input.toPlainText().strip()
        if not task or self._running:
            return

        self._running = True
        self._cancel_flag.clear()
        self._run_btn.setEnabled(False)
        self._status.setText("Nexus Coder: running...")
        self._status.setStyleSheet("color: #00c8ff; font-size: 11px; font-weight: bold;")
        self._output.clear()

        for i in range(len(STAGES)):
            self._set_stage(i, "⏳", "#666")

        def pipeline_thread():
            context = task
            for i, sd in enumerate(STAGES):
                if self._cancel_flag.is_set():
                    break
                self._set_stage(i, "▶", sd["color"])
                prompt = self._prompt_for(sd["id"], context)
                try:
                    result = self._query_model(sd["model"], prompt)
                    self._stage_outputs[sd["id"]] = result
                    self._set_stage(i, "✓", "#00cc66")
                    context = f"Previous stage ({sd['id']}):\n{result}\n\nFull task:\n{task}"
                except Exception as e:
                    self._stage_outputs[sd["id"]] = f"Error: {e}"
                    self._set_stage(i, "✗", "#ff4444")
                    context = f"Stage {sd['id']} failed: {e}\n\n{context}"

            QTimer.singleShot(0, self._pipeline_done)

        t = threading.Thread(target=pipeline_thread, daemon=True)
        t.start()

    def _prompt_for(self, stage_id: str, context: str) -> str:
        prompts = {
            "planner": f"You are a software architect. Plan the approach for this coding task. Break it into clear steps, identify what files need changing, and outline the implementation strategy.\n\nTask:\n{context}",
            "scrutinizer": f"You are a senior code reviewer. Scrutinize the following plan. Identify gaps, risks, edge cases, missing error handling, performance concerns, and architectural issues.\n\nPlan:\n{context}",
            "diff_generator": f"You are a senior developer. Based on the plan and review below, generate the actual code diffs. Use unified diff format (---/+++). Be precise about file paths, line numbers, and changes.\n\nInput:\n{context}",
            "tester": f"You are a testing specialist. Write tests for the code changes described below. Include unit tests, edge cases, and any integration test considerations.\n\nCode changes:\n{context}",
            "verifier": f"You are a QA engineer. Verify the code changes and tests below. Check for correctness, completeness, edge case coverage, and potential regressions.\n\nChanges and tests:\n{context}",
            "finalizer": f"You are a project lead. Review the entire pipeline output below: plan, scrutiny, diffs, tests, verification. Determine if the task is complete and safe to apply. Give a CLEAR PASS/FAIL/NEEDS_REVISION verdict.\n\nFull output:\n{context}",
        }
        return prompts.get(stage_id, f"Process this:\\n\\n{context}")

    def _pipeline_done(self):
        self._running = False
        self._run_btn.setEnabled(True)
        summary = self._stage_outputs.get("finalizer", "")
        if summary:
            lines = summary.split("\n")
            verdict = next((l for l in lines if "PASS" in l.upper() or "FAIL" in l.upper() or "REVISION" in l.upper()), "")
            self._output.clear()
            self._output.append(f"Verdict: {verdict}" if verdict else summary[:300])
        else:
            self._output.append("Pipeline finished.")
        self._status.setText("Nexus Coder: done")
        self._status.setStyleSheet("color: #00cc66; font-size: 11px; font-weight: bold;")

        # Push result to output socket
        for s in self._sockets:
            if s.label == "out":
                s.push_data({
                    "text": summary,
                    "stages": dict(self._stage_outputs),
                    "type": "nexus_coder_result",
                })

    def on_data_received(self, socket: SocketItem, data):
        if socket.label == "in":
            prompt = data.get("text", data.get("prompt", ""))
            if prompt:
                self._task_input.setPlainText(prompt)
                self._run_pipeline()

    def output_data(self, socket: SocketItem) -> dict:
        return {
            "text": self._stage_outputs.get("finalizer", ""),
            "stages": dict(self._stage_outputs),
            "type": "nexus_coder_result",
        }

    def serialize(self) -> dict:
        d = super().serialize()
        d["stages"] = dict(self._stage_outputs)
        return d

    def deserialize(self, data: dict):
        super().deserialize(data)
        self._stage_outputs = data.get("stages", {})
