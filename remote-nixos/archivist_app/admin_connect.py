from __future__ import annotations

import ctypes
import json
import os
import platform
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from app.config import DATA_DIR


STATE_FILE = DATA_DIR / "admin_easy_connect.json"
PAIR_CODE_TTL_SECONDS = 15 * 60


def _now() -> float:
    return time.time()


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict) -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state


def _pair_code() -> str:
    value = secrets.randbelow(900000) + 100000
    return f"{value // 1000:03d}-{value % 1000:03d}"


def _normalize_code(value: str | None) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 6:
        return None
    return f"{digits[:3]}-{digits[3:]}"


def _host_label(label: str | None = None) -> str:
    clean = (label or "").strip()
    return clean or platform.node() or "local-archivist"


def _public_state(state: dict) -> dict:
    expires_ts = float(state.get("expires_ts") or 0)
    expired = bool(expires_ts and expires_ts < _now())
    status = state.get("status") or "idle"
    if expired:
        status = "expired"
    local_code = state.get("local_code") if not expired else None
    remote_code = state.get("remote_code") if not expired else None
    return {
        "status": status,
        "local_code": local_code,
        "remote_code_received": bool(remote_code),
        "remote_host_label": state.get("remote_host_label") or "",
        "local_host_label": state.get("local_host_label") or _host_label(None),
        "created_ts": state.get("created_ts"),
        "expires_ts": expires_ts if not expired else None,
        "seconds_remaining": max(0, int(expires_ts - _now())) if expires_ts and not expired else 0,
        "pairing_ready": status == "pair_codes_exchanged" and bool(local_code and remote_code),
        "transport_enabled": False,
        "summary": _connect_summary(status, bool(local_code), bool(remote_code)),
        "next_steps": [
            "Both machines generate their own code.",
            "Each machine enters the other machine's code before any remote setup is allowed.",
            "After this clears, future transport will still require scoped capability approval before making changes.",
        ],
    }


def _connect_summary(status: str, has_local: bool, has_remote: bool) -> str:
    if status == "pair_codes_exchanged" and has_local and has_remote:
        return "Pair codes exchanged locally. The other machine must also enter this machine's code before transport should open."
    if status == "waiting_for_remote_code" and has_local:
        return "Local code generated. Enter the other machine's code to complete this side of the handshake."
    if status == "expired":
        return "Pairing code expired. Generate a fresh code before connecting."
    return "No active pairing code."


def easy_connect_status() -> dict:
    return _public_state(_read_state())


def start_easy_connect(host_label: str | None = None) -> dict:
    state = {
        "status": "waiting_for_remote_code",
        "local_code": _pair_code(),
        "remote_code": None,
        "local_host_label": _host_label(host_label),
        "remote_host_label": "",
        "created_ts": _now(),
        "expires_ts": _now() + PAIR_CODE_TTL_SECONDS,
        "capabilities": {
            "can_stage_remote_setup": False,
            "can_apply_remote_changes": False,
            "requires_audit_action": True,
            "requires_capability_scope": True,
        },
    }
    return _public_state(_write_state(state))


def verify_easy_connect(remote_code: str, host_label: str | None = None) -> dict:
    normalized = _normalize_code(remote_code)
    if not normalized:
        raise ValueError("Remote code must contain six digits.")
    state = _read_state()
    public = _public_state(state)
    if public["status"] in {"idle", "expired"} or not public.get("local_code"):
        raise ValueError("Generate this machine's code before entering a remote code.")
    if normalized == public["local_code"]:
        raise ValueError("Enter the other machine's code, not this machine's local code.")
    state["remote_code"] = normalized
    state["remote_host_label"] = _host_label(host_label or state.get("remote_host_label") or "remote-archivist")
    state["status"] = "pair_codes_exchanged"
    state["verified_ts"] = _now()
    return _public_state(_write_state(state))


def reset_easy_connect() -> dict:
    try:
        STATE_FILE.unlink()
    except FileNotFoundError:
        pass
    return easy_connect_status()


def _windows_memory_bytes() -> int | None:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys)


def _total_memory_bytes() -> int | None:
    if os.name == "nt":
        try:
            return _windows_memory_bytes()
        except Exception:
            return None
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size)
    except (ValueError, OSError, AttributeError):
        return None


def _run_command(args: list[str], timeout: int = 4) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


def _nvidia_gpus() -> list[dict]:
    if not shutil.which("nvidia-smi"):
        return []
    output = _run_command(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
        timeout=4,
    )
    gpus = []
    for line in output.splitlines():
        if not line.strip() or "," not in line:
            continue
        name, memory = [part.strip() for part in line.split(",", 1)]
        try:
            memory_mb = int(float(memory))
        except ValueError:
            memory_mb = 0
        gpus.append({"name": name, "memory_mb": memory_mb})
    return gpus


def _ollama_models() -> list[str]:
    if not shutil.which("ollama"):
        return []
    output = _run_command(["ollama", "list"], timeout=5)
    models = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def _profile_for_hardware(memory_gb: float | None, cpu_count: int, gpu_vram_gb: float) -> str:
    memory = memory_gb or 0
    if gpu_vram_gb >= 20 or memory >= 64:
        return "builder_plus"
    if gpu_vram_gb >= 10 or memory >= 32:
        return "full_local"
    if memory >= 16 and cpu_count >= 6:
        return "balanced"
    return "lite"


def _recommended_routes(profile: str) -> list[dict]:
    if profile == "builder_plus":
        return [
            {"env": "OLLAMA_ARCHIVIST_MODEL", "model": "RageBait/LadySophiaNoctua:latest", "reason": "archivist chat (persona, retrieval, memory)"},
            {"env": "OLLAMA_COWRITER_MODEL", "model": "gemma4:12b", "reason": "voice-preserving prose work"},
            {"env": "OLLAMA_CODER_MODEL", "model": "gemma4:12b", "reason": "broad code changes and script generation"},
            {"env": "OLLAMA_FAST_CODER_MODEL", "model": "minicpm-v4.6:latest", "reason": "small scripts and quick code turns"},
            {"env": "OLLAMA_MAINTENANCE_MODEL", "model": "gemma4:12b", "reason": "cheap maintenance chatter"},
            {"env": "OLLAMA_SUMMARY_MODEL", "model": "qwen3.5:0.8b", "reason": "index summaries"},
            {"env": "OLLAMA_VISION_MODEL", "model": "qwen3-vl:8b", "reason": "visual archive work"},
            {"env": "OLLAMA_EMBED_MODEL", "model": "nomic-embed-text:latest", "reason": "stable archive embeddings"},
        ]
    if profile == "full_local":
        return [
            {"env": "OLLAMA_ARCHIVIST_MODEL", "model": "RageBait/LadySophiaNoctua:latest", "reason": "archivist chat (persona, retrieval, memory)"},
            {"env": "OLLAMA_COWRITER_MODEL", "model": "gemma4:12b", "reason": "writing assistance"},
            {"env": "OLLAMA_CODER_MODEL", "model": "gemma4:12b", "reason": "practical code tasks"},
            {"env": "OLLAMA_FAST_CODER_MODEL", "model": "minicpm-v4.6:latest", "reason": "small scripts and quick code turns"},
            {"env": "OLLAMA_MAINTENANCE_MODEL", "model": "gemma4:12b", "reason": "fast background admin"},
            {"env": "OLLAMA_SUMMARY_MODEL", "model": "qwen3.5:0.8b", "reason": "document summaries"},
            {"env": "OLLAMA_VISION_MODEL", "model": "qwen3-vl:8b", "reason": "visual archive work"},
            {"env": "OLLAMA_EMBED_MODEL", "model": "nomic-embed-text:latest", "reason": "stable archive embeddings"},
        ]
    if profile == "balanced":
        return [
            {"env": "OLLAMA_ARCHIVIST_MODEL", "model": "RageBait/LadySophiaNoctua:latest", "reason": "archivist chat (persona, retrieval, memory)"},
            {"env": "OLLAMA_COWRITER_MODEL", "model": "gemma4:12b", "reason": "use only when writing quality matters"},
            {"env": "OLLAMA_CODER_MODEL", "model": "gemma4:12b", "reason": "small and medium code work"},
            {"env": "OLLAMA_MAINTENANCE_MODEL", "model": "gemma4:12b", "reason": "fast background admin"},
            {"env": "OLLAMA_SUMMARY_MODEL", "model": "qwen3.5:0.8b", "reason": "index summaries"},
            {"env": "OLLAMA_VISION_MODEL", "model": "minicpm-v4.6:latest", "reason": "lighter visual fallback"},
            {"env": "OLLAMA_EMBED_MODEL", "model": "nomic-embed-text:latest", "reason": "stable archive embeddings"},
        ]
    return [
        {"env": "OLLAMA_ARCHIVIST_MODEL", "model": "RageBait/LadySophiaNoctua:latest", "reason": "archivist chat (persona, retrieval, memory)"},
        {"env": "OLLAMA_COWRITER_MODEL", "model": "qwen2.5:7b", "reason": "lighter writing assistance"},
        {"env": "OLLAMA_CODER_MODEL", "model": "qwen2.5-coder:7b", "reason": "only load for explicit code work"},
        {"env": "OLLAMA_MAINTENANCE_MODEL", "model": "gemma4:12b", "reason": "cheap admin"},
        {"env": "OLLAMA_SUMMARY_MODEL", "model": "lfm2.5:8b", "reason": "minimum viable summaries"},
        {"env": "OLLAMA_EMBED_MODEL", "model": "nomic-embed-text:latest", "reason": "stable archive embeddings"},
    ]

def installer_profile() -> dict:
    memory_bytes = _total_memory_bytes()
    memory_gb = round(memory_bytes / (1024**3), 1) if memory_bytes else None
    cpu_count = os.cpu_count() or 1
    gpus = _nvidia_gpus()
    gpu_vram_gb = max((gpu.get("memory_mb", 0) for gpu in gpus), default=0) / 1024
    profile = _profile_for_hardware(memory_gb, cpu_count, gpu_vram_gb)
    recommended = _recommended_routes(profile)
    installed = set(_ollama_models())
    missing = sorted({route["model"] for route in recommended if route["model"] not in installed})
    return {
        "profile": profile,
        "profile_label": {
            "builder_plus": "Builder Plus",
            "full_local": "Full Local",
            "balanced": "Balanced",
            "lite": "Lite",
        }.get(profile, profile),
        "hardware": {
            "hostname": platform.node() or "unknown",
            "platform": platform.platform(),
            "cpu_count": cpu_count,
            "memory_gb": memory_gb,
            "gpus": gpus,
            "ollama_available": bool(shutil.which("ollama")),
            "installed_ollama_models": sorted(installed),
        },
        "recommended_env": recommended,
        "missing_models": missing,
        "pull_commands": [f"ollama pull {model}" for model in missing],
        "installer_plan": [
            "Detect CPU, memory, GPU VRAM, Ollama availability, and installed models.",
            "Choose the smallest model route set that preserves the Archivist experience on this hardware.",
            "Keep network and removable roots chat-ignored by default.",
            "Only make a remote root chat-aware after an approved worker can index local-to-data and sync metadata back.",
            "Use Easy Connect pair codes before staging remote changes, then require audited action confirmation.",
        ],
    }
